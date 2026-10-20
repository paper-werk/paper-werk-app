"""Pagination der API.

Die Parameter heißen wie bei Paperless-ngx (``?page=2&page_size=100``), damit
n8n-Workflows beide Systeme gleich ansprechen; die Pfade sind deutsch.
"""

from rest_framework.pagination import PageNumberPagination


class Seitenweise(PageNumberPagination):
    """Seitengröße 50, über ``page_size`` bis 500.

    Die Obergrenze verhindert, dass ``?page_size=999999`` die Pagination
    umgeht.
    """

    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 500
