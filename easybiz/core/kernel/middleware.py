class TenantStatusMiddleware:
    """Pass-through at M0; enforces tenant suspension in M4/M7."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)


class ModuleGateMiddleware:
    """Pass-through at M0; hides routes of disabled modules in M4."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)
