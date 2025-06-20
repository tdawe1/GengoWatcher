import os
import shutil
import subprocess

# --- Configuration ---
SCRIPT_NAME = "gengowatcher.py"
INI_TEMPLATE_NAME = "config template.ini"
README_NAME = "README.md"
RELEASE_DIR = "release"
DIST_DIR = "dist"
VERSION = "1.1.1"  # You can change this to the desired version number

# --- Build Process ---
def create_release():
    """Creates a new release for GengoWatcher."""

    print(f"Creating release version {VERSION}...")

    # 1. Create the .exe using PyInstaller
    print("Running PyInstaller to create the executable...")
    try:
        subprocess.run(
            [
                "pyinstaller",
                "--onefile",
                "--windowed", # Use --console if you have a command-line interface
                SCRIPT_NAME,
            ],
            check=True,
        )
    except FileNotFoundError:
        print(
            "Error: PyInstaller not found. Please install it using 'pip install pyinstaller'"
        )
        return
    except subprocess.CalledProcessError as e:
        print(f"Error during PyInstaller execution: {e}")
        return

    # 2. Create the release directory
    release_path = os.path.join(RELEASE_DIR, VERSION)
    os.makedirs(release_path, exist_ok=True)
    print(f"Created release directory: {release_path}")

    # 3. Copy over the necessary files
    print("Copying files to the release directory...")
    try:
        shutil.copy(SCRIPT_NAME, release_path)
        shutil.copy(INI_TEMPLATE_NAME, release_path)
        shutil.copy(README_NAME, release_path)
    except FileNotFoundError as e:
        print(f"Error copying files: {e}. Make sure the files exist in the root directory.")
        return

    # 4. Move the .exe to the release directory
    print("Moving the executable to the release directory...")
    try:
        exe_name = f"{os.path.splitext(SCRIPT_NAME)[0]}.exe"
        shutil.move(os.path.join(DIST_DIR, exe_name), release_path)
    except FileNotFoundError as e:
        print(f"Error moving the executable: {e}. Make sure the dist folder and the .exe exist.")
        return

    print("--- Release created successfully! ---")
    print(f"Files are located in: {release_path}")

if __name__ == "__main__":
    create_release()