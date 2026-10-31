from django.conf import settings


def store(request):
    return {"STORE": settings.STORE}
