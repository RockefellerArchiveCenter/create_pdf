#!/usr/bin/env python3

import logging
from os import getenv
from pathlib import Path
from requests import Session

import boto3
from textractor import Textractor

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class AlreadyProcessingError(Exception):
    pass

class AeonClient(object):
    def __init__(self, baseurl, access_key):
        self.session = Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'AeonClient/0.1',
            'X-AEON-API-KEY': access_key
        })
        self.baseurl = baseurl

    def get(self, url):
        full_url = "/".join([self.baseurl.rstrip("/"), url.lstrip("/")])
        return self.session.get(full_url)

class PdfCreator(object):

    def __init__(self):
        self.aeon_client = AeonClient()
        self.s3_client = boto3.client('s3') # TODO pass in credentials here
        self.extractor = Textractor() # TODO pass in credentials here

    def handle_new_transactions(self):
        """Main handler for function."""
        transactions_to_process = self.get_transactions_in_status(getenv('SOURCE_TRANSACTION_STATUS'))
        for transaction in transactions_to_process:
            try:
                lowercased = {k.lower(): v for k, v in transaction.items()}
                transaction_number = lowercased['transactionnumber']
                self.set_transaction_processing(transaction_number)
                pdf_path = self.create_pdf(transaction_number)
                self.optimize_pdf(pdf_path)
                self.update_transaction_status(transaction_number)
                self.set_transaction_finished(transaction_number)
            except AlreadyProcessingError:
                logging.error(f"Transaction {transaction_number} is already processing, skipping.")
            except Exception as e:
                logging.error(e)

    def set_transaction_processing(self, transaction_number):
        try:
            Path(getenv('IN_PROCESSING_FILE_DIR'), transaction_number).touch()
        except FileExistsError:
            raise AlreadyProcessingError()
        
    def set_transaction_finished(self, transaction_number):
        Path(getenv('IN_PROCESSING_FILE_DIR'), transaction_number).unlink()

    def create_pdf(self, transaction_number):
        root_dir = Path(getenv('ROOT_DIR'), transaction_number)
        pdf_path = root_dir / 'service_edited' / f'{transaction_number}.pdf'
        pdf_path.parent.mkdir(exist_ok=True)
        writer = PDFWriter(pdf_path)
        source_files = self.collect_tiff_filepaths(root_dir)
        for page_path in source_files:
            page_text = self.extract_text(page_path) # TODO return raw Textract and also plain text
            self.upload_page_text(page_text, page_path.name) # TODO upload Textract and also raw text?
            writer.append(page_path, page_text)
            # TODO concatenate text?
        writer.write()
        return pdf_path


    def collect_tiff_filepaths(self, root_dir):
        """Returns all TIFF files in the root directory.
        
        Args:
            root_dir (pathlib.Path): root directory of package.

        Returns:
            files (sorted list of pathlib.Path objects): TIFF files. 
        """
        master_edited_dir = root_dir / 'master_edited'
        master_dir = root_dir / 'master'
        file_list =  master_edited_dir.glob('*.tiff') if master_edited_dir.is_dir() else master_dir.glob('*.tiff')
        return sorted(list(file_list))


    def extract_text(self, page_path):
        """Extracts OCR text from page.
        
        Args:
            extractor (textractor.Textractor): Textractor client
            page_path (pathlib.Path): Page from which text should be extracted.

        Returns:
            text (dict): Text extracted from page by Amazon Textract.
        """
        # TODO review this and see if we shoudl be calling analyze_document or something else.
        text = self.extractor.detect_document_text(file_source=page_path)
        # TODO return plain text as well as raw Textract
        return text


    def upload_page_text(self, page_text, object_key):
        """Uploads extracted text from a page to an S3 bucket.
        
        Args:
            page_text (??): Extracted text from a page.
        """
        # Do we need to format first?
        # What object key are we using?
        self.s3_client.upload_file(
            page_text, 
            getenv('OCR_BUCKET'), 
            object_key, 
            ExtraArgs={'ContentType': 'text/plain'} # is this the correct content type?
        )

    def optimize_pdf(self, pdf_path):
        """Optimizes PDF.
        
        Args:
            pdf_path (pathlib.Path): path of PDF to be optimized.
        """
        pass


    def get_transactions_in_status(self, status_code):
        """Gets all transactions in an Aeon status.
        
        Args:
            client (AeonClient): client to interact with Aeon.
            status_code (str): status code of transactions.
        
        Returns:
            transactions (list of dicts): Aeon transactions matching the status code.
        """
        transaction_url = f"/odata/Requests?$filter=photoduplicationstatus eq {status_code}"
        return self.aeon_client.get(transaction_url).json()
        


    def update_transaction_status(self, transaction_number):
        """Updates status of an Aeon transaction.
        
        Args:
            client (AeonClient): client to interact with Aeon.
            transaction (dict): Aeon transaction.
        """
        transaction_url = f"/Requests/{transaction_number}/route"
        self.aeon_client.post(transaction_url, json={"newStatus": getenv('DESTINATION_TRANSACTION_STATUS')})
    

if __name__ == '__main__':
    PdfCreator().handle_new_transactions()