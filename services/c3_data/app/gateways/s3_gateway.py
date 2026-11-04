"""S3 clip reader for the pipeline (contract §5.3).

C3 reads clip objects that C1 wrote under ``tenants/.../{media_id}.{ext}``. Uses the shared
``homeai_common.s3`` client (respects ``AWS_ENDPOINT_URL`` for LocalStack).
"""

from __future__ import annotations

from homeai_common.s3 import s3_client


class S3ClipGateway:
    def __init__(self, bucket: str, region: str, endpoint_url: str | None = None):
        self.bucket = bucket
        self._client = s3_client(region, endpoint_url)

    def get_bytes(self, key: str) -> bytes:
        """Download the object body. Raises botocore ClientError if the key is missing."""
        obj = self._client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()
