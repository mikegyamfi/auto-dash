from django.apps import AppConfig


class AutodashAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'autodash_App'

    def ready(self):
        # this will import signals.py and register the handler above
        import autodash_App.signals
