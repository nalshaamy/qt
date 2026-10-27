"""Pure validators for public submissions. No Odoo dependency."""
import re
import unicodedata
from email.utils import parseaddr
from io import BytesIO
from zipfile import BadZipFile, ZipFile

MAX_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED = 30 * 1024 * 1024

class InvalidSubmission(ValueError):
    pass


def clean_text(value, *, limit=120, required=True):
    result = unicodedata.normalize('NFKC', str(value or '')).strip()
    result = re.sub(r'\s+', ' ', result)
    if any(unicodedata.category(c).startswith('C') for c in result):
        raise InvalidSubmission('Invalid control characters.')
    if len(result) > limit or (required and len(result) < 2):
        raise InvalidSubmission('Invalid text length.')
    return result


def normalize_phone(raw):
    phone = re.sub(r'[\s\-()]', '', str(raw or ''))
    if not re.fullmatch(r'\+?[0-9]{9,15}', phone):
        raise InvalidSubmission('Invalid phone number.')
    if phone.startswith('05') and len(phone) == 10:
        return '+966' + phone[1:]
    if phone.startswith('9665') and len(phone) == 12:
        return '+' + phone
    if phone.startswith('+9665') and len(phone) == 13:
        return phone
    raise InvalidSubmission('Enter a valid Saudi mobile phone number.')


def normalize_email(raw):
    value = str(raw or '').strip().lower()
    if not value:
        return ''
    _, address = parseaddr(value)
    if address != value or len(value) > 128 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        raise InvalidSubmission('Invalid email address.')
    return value


def experience_years(raw):
    if not re.fullmatch(r'\d{1,2}', str(raw or '')):
        raise InvalidSubmission('Experience must be a valid number.')
    years = int(raw)
    if years > 60:
        raise InvalidSubmission('Experience is outside the allowed range.')
    return years


def validate_document(name, content, max_bytes=MAX_BYTES, allowed=('pdf', 'docx')):
    """Structural screening, not an antivirus scan; never execute uploaded content."""
    if not isinstance(content, bytes) or not content or len(content) > max_bytes:
        raise InvalidSubmission('Invalid CV size.')
    filename = str(name or '')
    if '/' in filename or '\\' in filename or '\x00' in filename or len(filename) > 128:
        raise InvalidSubmission('Invalid file name.')
    if '.' not in filename:
        raise InvalidSubmission('Unsupported document format.')
    extension = filename.rsplit('.', 1)[-1].lower()
    if extension not in allowed:
        raise InvalidSubmission('Unsupported document format.')
    if extension == 'pdf':
        if not content.startswith(b'%PDF-') or b'%%EOF' not in content[-2048:]:
            raise InvalidSubmission('Invalid PDF document.')
        return 'application/pdf'
    if extension == 'docx':
        if not content.startswith(b'PK\x03\x04'):
            raise InvalidSubmission('Invalid DOCX document.')
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = archive.namelist()
                if len(names) > 500 or sum(f.file_size for f in archive.infolist()) > MAX_ARCHIVE_UNCOMPRESSED:
                    raise InvalidSubmission('Oversized DOCX archive.')
                if not {'[Content_Types].xml', 'word/document.xml'}.issubset(names):
                    raise InvalidSubmission('Malformed DOCX document.')
                if any(n.startswith('/') or '..' in n.split('/') for n in names):
                    raise InvalidSubmission('Unsafe DOCX archive path.')
                if any(n.lower().endswith(('.bin', '.exe', '.dll', '.vba', '.js', '.py')) or 'vbaProject' in n for n in names):
                    raise InvalidSubmission('Executable content is not accepted.')
        except (BadZipFile, RuntimeError, OSError) as exc:
            raise InvalidSubmission('Invalid DOCX document.') from exc
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    raise InvalidSubmission('Unsupported document format.')
