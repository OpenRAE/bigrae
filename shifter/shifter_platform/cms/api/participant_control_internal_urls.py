"""Private CMS workload routes, included only by the dedicated owner worker."""

from django.urls import path

from .participant_control_internal import (
    NativeInvocationBeginView,
    NativeInvocationFinishView,
    NativeInvocationWithdrawView,
)

urlpatterns = [
    path("begin/", NativeInvocationBeginView.as_view()),
    path("finish/", NativeInvocationFinishView.as_view()),
    path("withdraw/", NativeInvocationWithdrawView.as_view()),
]
