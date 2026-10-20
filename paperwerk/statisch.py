"""Storage der statischen Dateien im Betrieb, siehe paperwerk/settings/prod.py."""

from whitenoise.compress import Compressor
from whitenoise.storage import CompressedManifestStaticFilesStorage


class OhneBrotli(CompressedManifestStaticFilesStorage):
    """WhiteNoise-Storage nur mit gzip.

    WhiteNoise komprimiert mit Brotli, sobald das Paket importierbar ist, und
    WeasyPrint zieht es über fonttools immer mit. Brotli auf höchster Stufe
    kostete im Image-Build rund fünf Sekunden; im lokalen Netz reicht gzip.
    """

    def create_compressor(self, **kwargs):
        return Compressor(use_brotli=False, **kwargs)
