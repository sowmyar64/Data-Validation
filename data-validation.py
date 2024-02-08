import os
import sys
import zipfile
import logging as logger

# Configure logging
logger.basicConfig(filename='app.log', level=logger.DEBUG, format='%(asctime)s - %(message)s')


def extract_zip_files(folder_path):
    # Get list of files in the folder
    files = os.listdir(folder_path)

    # Filter only zip files
    zip_files = [file for file in files if file.endswith('.zip')]

    # Create a directory to extract each zip file
    for zip_file in zip_files:
        # Extract folder name from the zip file name
        folder_name = os.path.splitext(zip_file)[0]

        # Create folder if it doesn't exist
        extract_folder_path = os.path.join(folder_path, folder_name)
        os.makedirs(extract_folder_path, exist_ok=True)

        # Extract zip file contents to the folder
        with zipfile.ZipFile(os.path.join(folder_path, zip_file), 'r') as zip_ref:
            zip_ref.extractall(extract_folder_path)

    logger.info(f"Extracted {len(zip_files)} zip files.")


def main():
    # Check if input folder path is provided as a command-line argument
    if len(sys.argv) != 2:
        logger.error("Usage: python your_script.py <folder_path>")
        sys.exit(1)

    folder_path = sys.argv[1]

    # Check if the specified folder exists
    if not os.path.isdir(folder_path):
        logger.error(f"The specified folder '{folder_path}' does not exist.")
        sys.exit(1)

    extract_zip_files(folder_path)


if __name__ == "__main__":
    main()
