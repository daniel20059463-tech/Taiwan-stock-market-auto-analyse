import os
import re
import math

def scale_fonts(dir_path, scale_factor=1.25):
    pattern = re.compile(r'fontSize:\s*\"(\d+)px\"')
    
    for root, dirs, files in os.walk(dir_path):
        for file in files:
            if file.endswith(('.tsx', '.ts', '.jsx', '.js')):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                def repl(match):
                    original_size = int(match.group(1))
                    new_size = math.ceil(original_size * scale_factor)
                    return f'fontSize: "{new_size}px"'

                new_content = pattern.sub(repl, content)

                if new_content != content:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f'Updated {filepath}')

scale_fonts('src')
print('Done!')
