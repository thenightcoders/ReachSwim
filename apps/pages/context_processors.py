from .models import SiteConfig, FooterColumn


def site_context(request):
    """Inject global site data into every template."""
    config = SiteConfig.load()
    footer_columns = FooterColumn.objects.prefetch_related("links").all()

    return {
        "site_config": config,
        "footer_columns": footer_columns,
    }
