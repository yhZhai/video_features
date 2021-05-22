import os
import json
import argparse
from tqdm import tqdm

def main(path, subset='training', output='video_path.txt', json_path='hacs.json'):

    with open(json_path, 'r') as f:
        json_file = json.load(f)
        json_file = json_file['database']
        
    file_names = os.listdir(path)
    with open(output, 'w') as f:
        for file_name in tqdm(file_names):
            video_name = file_name[2:-4]
            if video_name in json_file.keys():
                if json_file[video_name]['subset'] == subset:
                    f.write('{}\n'.format(os.path.join(path, file_name)))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', type=str)
    parser.add_argument('--subset', type=str)
    parser.add_argument('--output_path', type=str)
    parser.add_argument('--json_file', type=str)
    opt = parser.parse_args()
    main(opt.path, opt.subset, opt.output_path, opt.json_file)

