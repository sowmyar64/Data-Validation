import sys
import logging as logger
from zip_extractor import ZipExtractor

# Configure logging
logger.basicConfig(filename='app.log', level=logger.DEBUG, format='%(asctime)s - %(message)s')


def main():
    logger.info("Process started normally")
    # Check if input and output folder paths are provided as command-line arguments
    if len(sys.argv) != 3:
        logger.error("Usage: python main.py <input_folder_path> <output_folder_path>")
        sys.exit(1)

    input_folder_path = sys.argv[1]
    output_folder_path = sys.argv[2]

    zip_extractor = ZipExtractor(input_folder_path, output_folder_path)
    zip_extractor.extract_zip_files()

    logger.info("Process successfully completed.")


if __name__ == "__main__":
    main()
