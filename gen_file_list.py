import os
import json
import argparse
from tqdm import tqdm

def main(path, output='video_path.txt', num_split=1):
    outputs = [open(output.replace('.', f'_{i}.'), 'w') for i in range(num_split)]
    file_names = os.listdir(path)
    for i, file_name in tqdm(enumerate(file_names)):
        outputs[int(i % num_split)].write('{}\n'.format(os.path.join(path, file_name)))

    for f in outputs:
        f.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--path', type=str)
    parser.add_argument('-o','--output_path', type=str)
    parser.add_argument('-n','--num_split', type=int, default=1)
    opt = parser.parse_args()
    main(opt.path, opt.output_path, opt.num_split)

