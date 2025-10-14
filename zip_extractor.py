import os
import sys
import zipfile
import logging as logger

# Configure logging
logger.basicConfig(filename='app.log', level=logger.DEBUG, format='%(asctime)s - %(message)s')


class ZipExtractor:
    def __init__(self, input_folder_path, output_folder_path):
        self.input_folder_path = input_folder_path
        self.output_folder_path = output_folder_path
        self.extracted_data_path = os.path.join(output_folder_path, 'extracted_data')

    def extract_zip_files(self):
        self._validate_input_folder()
        num_zip_files = self._count_zip_files()
        self._create_extracted_data_folder()
        self._extract_zip_files()
        self._validate_extraction(num_zip_files)

    def _validate_input_folder(self):
        if not os.path.isdir(self.input_folder_path):
            logger.error(f"The specified input folder '{self.input_folder_path}' does not exist.")
            sys.exit(1)
        logger.info(f"Input folder path: '{self.input_folder_path}'")

    def _count_zip_files(self):
        zip_files = [file for file in os.listdir(self.input_folder_path) if file.endswith('.zip')]
        num_zip_files = len(zip_files)
        logger.info(f"Number of zip files found in '{self.input_folder_path}': {num_zip_files}")
        return num_zip_files

    def _create_extracted_data_folder(self):
        os.makedirs(self.extracted_data_path, exist_ok=True)
        logger.info(f"Created extracted data folder: '{self.extracted_data_path}'")

    def _extract_zip_files(self):
        logger.info("Process starts to extract zip files")
        for file_name in os.listdir(self.input_folder_path):
            if file_name.endswith('.zip'):
                zip_file_path = os.path.join(self.input_folder_path, file_name)
                folder_name = os.path.splitext(file_name)[0]
                extraction_folder = os.path.join(self.extracted_data_path, folder_name)
                self._unzip(zip_file_path, extraction_folder)

    def _unzip(self, zip_file_path, extraction_folder):
        logger.info(f"Extracting '{zip_file_path}' to '{extraction_folder}'")
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            zip_ref.extractall(extraction_folder)
        logger.info(f"Extraction completed for '{zip_file_path}'")

    def _validate_extraction(self, num_zip_files):
        num_extracted_folders = len([name for name in os.listdir(self.extracted_data_path)
                                     if os.path.isdir(os.path.join(self.extracted_data_path, name))])
        if num_zip_files != num_extracted_folders:
            logger.error("Number of extracted folders does not match number of zip files.")
            sys.exit(1)
        logger.info(f"Successfully extracted {num_zip_files} zip files.")
