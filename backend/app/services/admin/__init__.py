"""Administrative services, grouped into responsibility subpackages (``provider``, ``project``, ``connector``,
``engineering_knowledge``, ``governance``, ``panel``, ``task``).

Public modules follow the ``admin_*_service.py`` convention and are imported from their subpackage
(``from app.services.admin.provider import admin_provider_service``); private ``_admin_*`` modules are imported
only from within this package.
"""
