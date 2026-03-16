import os
import re

def process_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return False
    
    if 'utcnow()' not in content and 'utcnow' not in content:
        return False
        
    # Replace datetime.utcnow()
    new_content = re.sub(r'datetime\.utcnow\(\)', 'datetime.now(timezone.utc)', content)
    
    if content != new_content:
        # Needs timezone import if not present
        if 'timezone' not in new_content:
            # Find from datetime import ...
            if re.search(r'from datetime import([^\n]*)(datetime|timedelta|date)', new_content):
                # Add timezone to the matching line
                new_content = re.sub(r'(from datetime import[^\n]*)(datetime|timedelta|date)', r'\1\2, timezone', new_content, count=1)
            else:
                new_content = 'from datetime import timezone\n' + new_content

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

root_dir = r'c:\Users\Sebastian\Desktop\Curym\BackEnd\app'
modified = 0
for dirpath, _, filenames in os.walk(root_dir):
    for filename in filenames:
        if filename.endswith('.py'):
            filepath = os.path.join(dirpath, filename)
            if process_file(filepath):
                modified += 1
                print(f"Modified {filepath}")
print(f"Total modified: {modified}")
