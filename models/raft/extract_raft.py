import os
from models.raft.transforms.transforms import ResizeImproved, ToTensorWithoutScaling, ToFloat
from typing import Dict, Union

import cv2
import numpy as np
import torch
from tqdm import tqdm
import torch.nn.functional as F
import torchvision.transforms as transforms
from utils.utils import (action_on_extraction, form_list_from_user_input,
                         reencode_video_with_diff_fps)
from models.raft.raft_src.raft import RAFT
import models.raft.raft_src.utils.flow_viz as flow_viz
import traceback


class InputPadder:
    """ Pads images such that dimensions are divisible by 8
    Reference: https://github.com/princeton-vl/RAFT/tree/25eb2ac723c36865c636c9d1f497af8023981868"""
    def __init__(self, dims, mode='sintel'):
        self.ht, self.wd = dims[-2:]
        pad_ht = (((self.ht // 8) + 1) * 8 - self.ht) % 8
        pad_wd = (((self.wd // 8) + 1) * 8 - self.wd) % 8
        if mode == 'sintel':
            self._pad = [pad_wd//2, pad_wd - pad_wd//2, pad_ht//2, pad_ht - pad_ht//2]
        else:
            self._pad = [pad_wd//2, pad_wd - pad_wd//2, 0, pad_ht]

    def pad(self, input):
        return F.pad(input, self._pad, mode='replicate')

    def unpad(self, x):
        ht, wd = x.shape[-2:]
        c = [self._pad[2], ht-self._pad[3], self._pad[0], wd-self._pad[1]]
        return x[..., c[0]:c[1], c[2]:c[3]]


class ExtractRAFT(torch.nn.Module):

    def __init__(self, args):
        super(ExtractRAFT, self).__init__()
        self.feature_type = args.feature_type
        self.path_list = form_list_from_user_input(args)
        self.model_is_small = False
        # self.model_path = './models/raft/checkpoints/raft-kitti.pth'
        self.model_path = './models/raft/checkpoints/raft-sintel.pth'
        self.batch_size = args.batch_size
        self.extraction_fps = args.extraction_fps
        self.resize_to_smaller_edge = args.resize_to_smaller_edge
        self.side_size = args.side_size
        if self.side_size is not None:
            self.transforms = transforms.Compose([
                transforms.ToPILImage(),
                ResizeImproved(self.side_size, self.resize_to_smaller_edge),
                transforms.PILToTensor(),
                ToFloat(),
            ])
        else:
            self.transforms = transforms.Compose([
                ToTensorWithoutScaling()
            ])
        self.show_pred = args.show_pred
        self.keep_tmp_files = args.keep_tmp_files
        self.extraction_fps = args.extraction_fps
        self.on_extraction = args.on_extraction
        self.tmp_path = os.path.join(args.tmp_path, self.feature_type)
        self.output_path = os.path.join(args.output_path, self.feature_type)
        self.progress = tqdm(total=len(self.path_list))

    def forward(self, indices: torch.LongTensor):
        '''
        Arguments:
            indices {torch.LongTensor} -- indices to self.path_list
        '''
        device = indices.device

        # load the model
        model = RAFT(self.model_is_small)
        model = torch.nn.DataParallel(model, device_ids=[device])
        model.load_state_dict(torch.load(self.model_path, map_location=device))
        # model = model.module
        model.to(device)
        model.eval()

        for idx in indices:
            # when error occurs might fail silently when run from torch data parallel
            try:
                feats_dict = self.extract(device, model, self.path_list[idx])
                action_on_extraction(feats_dict, self.path_list[idx], self.output_path, self.on_extraction)
            except KeyboardInterrupt:
                raise KeyboardInterrupt
            except Exception as e:
                # prints only the last line of an error. Use `traceback.print_exc()` for the whole traceback
                traceback.print_exc()
                print(e)
                print(f'Extraction failed at: {self.path_list[idx]} with error (↑). Continuing extraction')

            # update tqdm progress bar
            self.progress.update()

    def extract(self, device: torch.device, model: torch.nn.Module,
                video_path: Union[str, None] = None) -> Dict[str, np.ndarray]:
        '''The extraction call. Made to clean the forward call a bit.

        Arguments:
            device {torch.device}
            model {torch.nn.Module}

        Keyword Arguments:
            video_path {Union[str, None]} -- if you would like to use import it and use it as
                                             "path -> model"-fashion (default: {None})

        Returns:
            Dict[str, np.ndarray]: 'features_name', 'fps', 'timestamps_ms'
        '''
        def _run_on_a_batch(flow_frames, batch, model, device, padder):
            batch = torch.cat(batch).to(device)
            batch = padder.pad(batch)

            with torch.no_grad():
                flow_low, flow_up = model(batch[:-1], batch[1:], iters=20, test_mode=True)
                # upadding only before saving because np.concat will not work if the img is unpadded
                flow_frames.extend(padder.unpad(flow_up).tolist())
                # show optical flow along with rgb frames
                if self.show_pred:
                    self.show_flow_for_every_pair_of_frames(flow_up, batch)

        # take the video, change fps and save to the tmp folder
        if self.extraction_fps is not None:
            video_path = reencode_video_with_diff_fps(video_path, self.tmp_path, self.extraction_fps)

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        timestamps_ms = []
        batch = []
        flow_frames = []

        # sometimes when the target fps is 1 or 2, the first frame of the reencoded video is missing
        # and cap.read returns None but the rest of the frames are ok. timestep is 0.0 for the 2nd frame in
        # this case
        first_frame = True
        # we use None to check if we are just started to extract frames
        padder = None
        while cap.isOpened():
            frame_exists, rgb = cap.read()

            if first_frame:
                first_frame = False
                if frame_exists is False:
                    continue

            if frame_exists:
                timestamps_ms.append(cap.get(cv2.CAP_PROP_POS_MSEC))
                # preprocess the image
                rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
                rgb = self.transforms(rgb)
                rgb = rgb.unsqueeze(0)

                if padder is None:
                    padder = InputPadder(rgb.shape)

                batch.append(rgb)

                # - 1 is used because we need B+1 frames to calculate B frames
                if len(batch) - 1 == self.batch_size:
                    _run_on_a_batch(flow_frames, batch, model, device, padder)
                    # leaving the last element to calculate flow between it and the first element
                    batch = [batch[-1]]
            else:
                if len(batch) > 1:
                    _run_on_a_batch(flow_frames, batch, model, device, padder)
                cap.release()
                break

        # removes the video with different fps to preserve disk space
        if (self.extraction_fps is not None) and (not self.keep_tmp_files):
            os.remove(video_path)

        features_with_meta = {
            self.feature_type: np.array(flow_frames),
            'fps': np.array(fps),
            'timestamps_ms': np.array(timestamps_ms)
        }

        return features_with_meta

    def show_flow_for_every_pair_of_frames(self, flow_up: torch.Tensor, batch: torch.Tensor):
        '''Shows the resulting flow as well as the first frame

        Args:
            flow_up (torch.Tensor): the output of the RAFT
            batch (torch.Tensor): the stack of rgb inputs
        '''
        for idx, flow in enumerate(flow_up):
            img = batch[idx].permute(1, 2, 0).cpu().numpy()
            flow = flow.permute(1, 2, 0).cpu().numpy()
            flow = flow_viz.flow_to_image(flow)
            img_flow = np.concatenate([img, flow], axis=0)
            cv2.imshow('Press any key to see the next frame...', img_flow[:, :, [2, 1, 0]] / 255.0)
            cv2.waitKey()