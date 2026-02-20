
def fix_file(path):
    print(f"Fixing {path}...")
    with open(path, "r") as f:
        lines = f.readlines()

    new_lines = []
    in_try = False
    in_except = False
    
    for line in lines:
        if line.strip() == "try:":
            in_try = True
            new_lines.append(line)
            continue
        
        if line.strip().startswith("except Exception as e:"):
            in_try = False
            in_except = True
            new_lines.append(line)
            continue
            
        if in_try:
            # Check if line is already indented relative to try
            # My bad patch didn't indent at all
            # So I need to add indentation.
            # But I need to respect existing indentation?
            # Existing indentation was correct for the original line.
            # 'try:' has same indentation as original line.
            # So original line needs 4 spaces more.
            # But 'import os' which I added also needs indentation.
            if "import os" in line:
                 # I added '    import os\n' but maybe not enough?
                 # No, I access indent variable in my script
                 pass
            
            # Smart fix: just add 4 spaces to everything inside try/except block 
            # if it looks like it belongs there
            if "self._cursor.execute" in line or "import os" in line:
                 # But wait, I added `indent + "try:"`
                 # And `indent + "import os"`
                 # And `line` (which has `indent + content`)
                 
                 # So `try` and `line` have SAME indent.
                 # Python requires `line` to have `indent + 4`.
                 # So I need to add 4 spaces to `line` and `import os`.
                 
                 # How to detect "indent"? 
                 # Just use the indentation of "try:" + 4 spaces.
                 pass

    # Easier approach:
    # Just undo the patch.
    # Remove lines containing "try:", "import os", "except Exception", "DEBUG SQL FAIL", "raise"
    # if they match my specific pattern.
    
    final_lines = []
    for line in lines:
        s = line.strip()
        if s == "try:": continue
        if s == "import os" and "database.py" in path: continue # careful
        if s.startswith("except Exception as e:"): continue
        if "DEBUG SQL FAIL" in line: continue
        if s == "raise": continue
        
        # For mariadb
        if "DEBUG CONNECT PID" in line: continue
        if s == "import os" and "mariadb" in path: continue
        
        final_lines.append(line)
        
    with open(path, "w") as f:
        f.writelines(final_lines)
    print("Reverted.")

fix_file("apps/frappe/frappe/database/database.py")
fix_file("apps/frappe/frappe/database/mariadb/database.py")
