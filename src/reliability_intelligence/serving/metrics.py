"""Per-application process-local metrics with fixed, bounded labels."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class ApplicationMetrics:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.http = Counter(
            "rip_http_requests",
            "HTTP requests",
            ["method", "route", "status_class"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "rip_http_request_seconds", "HTTP duration", ["method", "route"], registry=self.registry
        )
        self.telemetry = Counter(
            "rip_telemetry_rows", "Telemetry rows", ["outcome"], registry=self.registry
        )
        self.predictions = Counter(
            "rip_predictions", "Prediction operations", ["outcome"], registry=self.registry
        )
        self.inference = Histogram(
            "rip_prediction_seconds",
            "Prediction operation duration including storage",
            registry=self.registry,
        )
        self.failures = Counter(
            "rip_dependency_failures", "Dependency errors", ["dependency"], registry=self.registry
        )
        self.rejections = Counter(
            "rip_rejected_requests", "Rejected requests", ["route"], registry=self.registry
        )
        self.readiness = Gauge(
            "rip_ready", "Last readiness check (0 until checked)", registry=self.registry
        )


def route_label(request):
    route = request.scope.get("route")
    return route.path if route is not None else "unmatched"
