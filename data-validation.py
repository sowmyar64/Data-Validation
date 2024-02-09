import os
import sys
import zipfile
import logging as logger

# Configure logging
logger.basicConfig(filename='app.log', level=logger.DEBUG, format='%(asctime)s - %(message)s')


def unzip(zip_file_path, extraction_folder):
    logger.info(f"Extracting '{zip_file_path}' to '{extraction_folder}'")
    with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
        zip_ref.extractall(extraction_folder)
    logger.info(f"Extraction completed for '{zip_file_path}'")


def count_zip_files(folder_path):
    logger.debug(f"Counting zip files in '{folder_path}'")
    zip_files = [file for file in os.listdir(folder_path) if file.endswith('.zip')]
    num_zip_files = len(zip_files)
    logger.info(f"Number of zip files found in '{folder_path}': {num_zip_files}")
    return num_zip_files


def create_extracted_data_folder(extracted_data_path):
    os.makedirs(extracted_data_path, exist_ok=True)


def validate(zip_count, extracted_folder_count):
    logger.debug(f"Validating zip count: {zip_count}, extracted folder count: {extracted_folder_count}")
    return zip_count == extracted_folder_count


def main():
    logger.info("Process started normally")
    # Check if input and output folder paths are provided as command-line arguments
    if len(sys.argv) != 3:
        logger.error("Usage: python your_script.py <input_folder_path> <output_folder_path>")
        sys.exit(1)

    input_folder_path = sys.argv[1]
    output_folder_path = sys.argv[2]

    # Check if the specified input folder exists
    if not os.path.isdir(input_folder_path):
        logger.error(f"The specified input folder '{input_folder_path}' does not exist.")
        sys.exit(1)

    logger.info(f"Input folder path: '{input_folder_path}'")
    logger.info(f"Output folder path: '{output_folder_path}'")

    # Count the number of zip files in the input folder
    logger.info("Process starts to count zip files")
    num_zip_files = count_zip_files(input_folder_path)
    logger.info(f"Number of zip files to extract: {num_zip_files}")

    # Create the extracted data folder
    extracted_data_path = os.path.join(output_folder_path, 'extracted_data')
    create_extracted_data_folder(extracted_data_path)

    # Extract each zip file into its own folder within the extracted data folder
    logger.info("Process starts to extract zip files")
    for file_name in os.listdir(input_folder_path):
        if file_name.endswith('.zip'):
            zip_file_path = os.path.join(input_folder_path, file_name)
            folder_name = os.path.splitext(file_name)[0]
            extraction_folder = os.path.join(extracted_data_path, folder_name)
            unzip(zip_file_path, extraction_folder)

    # Count the number of folders in the extracted data folder
    logger.info("Process starts to count extracted folders")
    num_extracted_folders = len([name for name in os.listdir(extracted_data_path)
                                 if os.path.isdir(os.path.join(extracted_data_path, name))])

    # Validate the number of extracted folders
    logger.info("Process starts to validate")
    if not validate(num_zip_files, num_extracted_folders):
        logger.error("Number of extracted folders does not match number of zip files.")
        sys.exit(1)

    logger.info(f"Successfully extracted {num_zip_files} zip files.")
    logger.info("Process successfully completed.")


if __name__ == "__main__":
    main()
