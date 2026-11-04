"""``core.adminhilfen.jquery_entdoppeln`` mit und ohne Hash in den URLs."""

import pytest
from django import forms
from django.contrib.staticfiles.storage import StaticFilesStorage

from core.adminhilfen import jquery_entdoppeln

JQUERY = 'admin/js/vendor/jquery/jquery.js'
JQUERY_MIN = 'admin/js/vendor/jquery/jquery.min.js'


class StorageMitHash(StaticFilesStorage):
    """Setzt einen Hash in den Dateinamen wie ``ManifestStaticFilesStorage``,
    ohne Manifest und ``collectstatic``."""

    def url(self, name):
        stamm, _, endung = name.rpartition('.')
        return super().url(f'{stamm}.2c872dbe60f4.{endung}')


def _skripte(media):
    return [str(datei) for datei in media._js]


@pytest.fixture(params=['ohne Hash', 'mit Hash'])
def storage(request, settings):
    if request.param == 'mit Hash':
        settings.STORAGES = {
            **settings.STORAGES,
            'staticfiles': {
                'BACKEND': f'{__name__}.StorageMitHash'},
        }


@pytest.mark.parametrize('extra, bleibt, entfaellt', [
    ('.min', 'jquery.min.', 'jquery.js'),
    ('', 'jquery.js', 'jquery.min.'),
])
def test_genau_ein_jquery_bleibt(storage, extra, bleibt, entfaellt):
    """Behalten wird die Datei, die Django gewählt hätte, auch wenn der
    Storage einen Hash in die URL setzt (Container)."""
    media = forms.Media(js=[forms.Script(JQUERY), forms.Script(JQUERY_MIN),
                            'admin/js/jquery.init.js'])

    skripte = _skripte(jquery_entdoppeln(media, extra))

    jquery = [s for s in skripte if 'vendor/jquery/jquery' in s]
    assert len(jquery) == 1
    assert bleibt.rstrip('.') in jquery[0].replace('.2c872dbe60f4', '')
    assert entfaellt not in jquery[0].replace('.2c872dbe60f4', '')
    assert any('jquery.init' in s for s in skripte)
