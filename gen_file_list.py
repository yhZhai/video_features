import os
import json
import argparse
from tqdm import tqdm

def main(path, output='video_path.txt', subset='training',
         json_path='hacs.json'):
    search_valid_video = subset and json_path
    if search_valid_video:
        with open(json_path, 'r') as f:
            json_file = json.load(f)
            json_file = json_file['database']
        
    file_names = os.listdir(path)
    with open(output, 'w') as f:
        for file_name in tqdm(file_names):
            video_name = file_name[2:-4]
            if search_valid_video:
                if video_name in json_file.keys():
                    if json_file[video_name]['subset'] == subset:
                        f.write('{}\n'.format(os.path.join(path, file_name)))
            else:
                f.write('{}\n'.format(os.path.join(path, file_name)))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--path', type=str)
    parser.add_argument('-o', '--output_path', type=str)
    parser.add_argument('--subset', type=str, default=None)
    parser.add_argument('--json_file', type=str, default=None)
    opt = parser.parse_args()
    main(opt.path, opt.output_path, opt.subset, opt.json_file)

