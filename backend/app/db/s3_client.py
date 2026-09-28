import os
import boto3
from botocore.config import Config
from app.core.config import settings
import logging

# Prevent boto3 from hanging 20s trying to reach AWS EC2 metadata on local machines
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"

logger = logging.getLogger(__name__)

s3_client = None


def get_s3_client():
    global s3_client
    if s3_client is None:
        if not settings.s3_bucket_url or not settings.s3_access_key or not settings.s3_secret_key:
            logger.warning("S3 bucket URL, Access Key, or Secret Key not configured")
            return None
        try:
            s3_client = boto3.client(
                's3',
                endpoint_url=settings.s3_bucket_url,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                config=Config(
                    signature_version='s3v4',
                    connect_timeout=2,
                    read_timeout=3,
                    retries={'max_attempts': 1}
                ),
                region_name='us-east-1'
            )
            logger.info("S3 client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            return None
    return s3_client


def init_s3():
    return get_s3_client()