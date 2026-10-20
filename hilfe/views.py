from django.contrib import admin
from django.shortcuts import render

from .texte import anleitung


def seite(request):
    """``/hilfe/``: die ganze Anleitung auf einer Seite, links das
    Inhaltsverzeichnis. Eine Seite, damit jeder Anker unter derselben URL
    liegt und die Browsersuche alles findet. Verworfen: eine Seite je
    Kapitel."""
    return render(request, 'hilfe/seite.html', {
        **admin.site.each_context(request),
        'title': 'Bedienungsanleitung',
        'anleitung': anleitung(),
    })
