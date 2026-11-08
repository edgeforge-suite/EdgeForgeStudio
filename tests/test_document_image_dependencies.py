"""Exercise the shipped parser helpers and verified TLS clients with synthetic data."""
from __future__ import annotations

import io
import ssl
from ipaddress import ip_address

import certifi
import httpx
import httpx2
import pdfplumber
import pytest
from docx import Document
from pdfplumber.utils.exceptions import PdfminerException
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as SpreadsheetImage
from PIL import Image, UnidentifiedImageError

from app.services.openapi_fetch_guard import _PinnedHTTPSConnection


def _png() -> io.BytesIO:
    data = io.BytesIO()
    Image.new("RGB", (24, 16), (31, 63, 127)).save(data, format="PNG")
    data.seek(0)
    return data


@pytest.mark.parametrize("format", ["PNG", "JPEG", "TIFF", "GIF"])
def test_shipped_image_codecs_decode_synthetic_content(format: str) -> None:
    data = io.BytesIO()
    Image.new("RGB", (24, 16), (31, 63, 127)).save(data, format=format)
    data.seek(0)
    with Image.open(data) as image:
        image.load()
        assert image.size == (24, 16)
        assert image.convert("RGB").getpixel((0, 0)) == pytest.approx((31, 63, 127), abs=2)


def test_pdfplumber_renders_a_synthetic_pdf_through_pillow() -> None:
    data = io.BytesIO()
    with Image.open(_png()) as image:
        image.save(data, format="PDF")
    data.seek(0)
    with pdfplumber.open(data) as document:
        assert len(document.pages) == 1
        rendered = document.pages[0].to_image(resolution=72)
        assert rendered.original.size == (24, 16)
        rendered.original.load()


def test_spreadsheet_and_word_helpers_roundtrip_embedded_image() -> None:
    workbook = Workbook()
    workbook.active["A1"] = "Synthetic fixture"
    workbook.active.add_image(SpreadsheetImage(_png()), "B2")
    spreadsheet = io.BytesIO()
    workbook.save(spreadsheet)
    spreadsheet.seek(0)
    reopened = load_workbook(spreadsheet)
    assert reopened.active["A1"].value == "Synthetic fixture"
    assert len(reopened.active._images) == 1
    assert reopened.active._images[0].width == 24
    document = Document()
    document.add_paragraph("Synthetic fixture")
    document.add_picture(_png())
    word = io.BytesIO()
    document.save(word)
    word.seek(0)
    reopened_document = Document(word)
    assert len(reopened_document.inline_shapes) == 1
    assert reopened_document.paragraphs[0].text == "Synthetic fixture"


def test_image_and_document_helpers_reject_invalid_content() -> None:
    with pytest.raises(UnidentifiedImageError):
        Image.open(io.BytesIO(b"synthetic invalid image"))
    with pytest.raises(PdfminerException):
        pdfplumber.open(io.BytesIO(b"synthetic invalid PDF"))
    with pytest.raises(UnidentifiedImageError):
        SpreadsheetImage(io.BytesIO(b"synthetic invalid image"))


def test_certifi_bundle_loads_and_http_clients_keep_verification_enabled() -> None:
    context = ssl.create_default_context(cafile=certifi.where())
    assert context.cert_store_stats()["x509_ca"] > 0
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    subjects = str([certificate["subject"] for certificate in context.get_ca_certs()])
    assert "emSign ECC Root CA - G3" not in subjects
    assert "emSign Root CA - G1" in subjects
    guarded = _PinnedHTTPSConnection(
        "synthetic.invalid", pinned_addresses=(ip_address("192.0.2.1"),)
    )
    assert guarded._context.verify_mode == ssl.CERT_REQUIRED
    assert guarded._context.check_hostname
    for client_class in (httpx.Client, httpx2.Client):
        with client_class(trust_env=False) as client:
            # Inspect the actual default pool context, rather than passing a
            # proof-only context that could conceal changed client defaults.
            actual = client._transport._pool._ssl_context
            assert actual.verify_mode == ssl.CERT_REQUIRED
            assert actual.check_hostname
            # httpx2 uses the platform truststore context, which deliberately
            # does not expose cert_store_stats on every supported platform.
            if client_class is httpx.Client:
                assert actual.cert_store_stats()["x509_ca"] > 0


async def test_runtime_async_http_client_keeps_verification_enabled() -> None:
    async with httpx.AsyncClient(trust_env=False) as client:
        context = client._transport._pool._ssl_context
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
