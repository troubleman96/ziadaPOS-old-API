"""
Management command: test_minio

Tests the MinIO connection, verifies bucket existence (creates it if missing),
uploads a small test object, reads it back, then cleans up.

Usage:
    python manage.py test_minio
    python manage.py test_minio --no-cleanup   # leave test object in bucket
"""

import io
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verify MinIO connectivity: connect, list/create bucket, upload, download, delete."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-cleanup",
            action="store_true",
            help="Skip deleting the test object after the upload/download test.",
        )

    def handle(self, *args, **options):
        try:
            import boto3
            from botocore.client import Config
            from botocore.exceptions import ClientError
        except ImportError:
            raise CommandError("boto3 is not installed. Run: pip install boto3")

        endpoint   = getattr(settings, "MINIO_ENDPOINT_URL", None) or settings.__dict__.get("MINIO_ENDPOINT_URL")
        access_key = None
        secret_key = None
        bucket     = "ziada"

        # Try to read directly from env in case settings isn't fully loaded
        if not endpoint:
            from decouple import config as env_config
            endpoint   = env_config("MINIO_ENDPOINT_URL", default="https://media.camelcreatives.com")
            access_key = env_config("MINIO_ACCESS_KEY",   default="")
            secret_key = env_config("MINIO_SECRET_KEY",   default="")
            bucket     = env_config("MINIO_BUCKET_NAME",  default="ziada")
        else:
            from decouple import config as env_config
            access_key = env_config("MINIO_ACCESS_KEY",   default="")
            secret_key = env_config("MINIO_SECRET_KEY",   default="")
            bucket     = env_config("MINIO_BUCKET_NAME",  default="ziada")

        self.stdout.write(f"  Endpoint : {endpoint}")
        self.stdout.write(f"  Bucket   : {bucket}")
        self.stdout.write(f"  Key      : {access_key[:4]}****" if access_key else "  Key      : (not set)")
        self.stdout.write("")

        # ── 1. Connect ────────────────────────────────────────────────────────
        self.stdout.write("① Connecting to MinIO… ", ending="")
        try:
            s3 = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=10,
                    read_timeout=10,
                    s3={"addressing_style": "path"},
                ),
                region_name="us-east-1",
            )
            s3.list_buckets()
            self.stdout.write(self.style.SUCCESS("OK"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"FAILED"))
            raise CommandError(
                f"Cannot reach MinIO at {endpoint}.\n"
                f"Error: {exc}\n\n"
                "Ensure the Nginx S3 API proxy block is configured (see deploy.md § MinIO)."
            )

        # ── 2. Ensure bucket exists ───────────────────────────────────────────
        self.stdout.write(f"② Checking bucket '{bucket}'… ", ending="")
        try:
            s3.head_bucket(Bucket=bucket)
            self.stdout.write(self.style.SUCCESS("exists"))
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("404", "NoSuchBucket"):
                self.stdout.write("not found — creating… ", ending="")
                try:
                    s3.create_bucket(Bucket=bucket)
                    # Make bucket publicly readable
                    s3.put_bucket_acl(Bucket=bucket, ACL="public-read")
                    self.stdout.write(self.style.SUCCESS("created"))
                except Exception as create_exc:
                    self.stdout.write(self.style.ERROR("FAILED"))
                    raise CommandError(f"Could not create bucket: {create_exc}")
            else:
                self.stdout.write(self.style.ERROR("FAILED"))
                raise CommandError(f"Bucket check failed: {exc}")

        # ── 3. Upload test object ─────────────────────────────────────────────
        test_key  = f"_ziada_test_{uuid.uuid4().hex[:8]}.txt"
        test_body = b"Ziada POS MinIO connectivity test - safe to delete."
        self.stdout.write(f"③ Uploading test object '{test_key}'… ", ending="")
        try:
            s3.put_object(Bucket=bucket, Key=test_key, Body=test_body, ContentType="text/plain")
            self.stdout.write(self.style.SUCCESS("OK"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR("FAILED"))
            raise CommandError(f"Upload failed: {exc}")

        # ── 4. Download and verify ────────────────────────────────────────────
        self.stdout.write("④ Downloading and verifying… ", ending="")
        try:
            resp = s3.get_object(Bucket=bucket, Key=test_key)
            body = resp["Body"].read()
            assert body == test_body, "Content mismatch!"
            self.stdout.write(self.style.SUCCESS("OK"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR("FAILED"))
            raise CommandError(f"Download/verify failed: {exc}")

        # ── 5. Public URL check ───────────────────────────────────────────────
        public_url = f"{endpoint.rstrip('/')}/{bucket}/{test_key}"
        self.stdout.write(f"⑤ Public URL: {public_url}")

        # ── 6. Cleanup ────────────────────────────────────────────────────────
        if options["no_cleanup"]:
            self.stdout.write(self.style.WARNING(f"   Skipped cleanup — object left in bucket."))
        else:
            self.stdout.write("⑥ Cleaning up… ", ending="")
            try:
                s3.delete_object(Bucket=bucket, Key=test_key)
                self.stdout.write(self.style.SUCCESS("OK"))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"cleanup failed (non-fatal): {exc}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("✓ MinIO storage is working correctly."))
        self.stdout.write("")
        self.stdout.write("  Next step: set USE_MINIO=True in .env to activate for Django.")
