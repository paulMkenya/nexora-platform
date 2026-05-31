"""
Webhook endpoint management (admin only) and delivery log.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from public_api.models import WebhookDelivery, WebhookEndpoint
from public_api.serializers import WebhookDeliverySerializer, WebhookEndpointSerializer
from public_api.throttling import APIKeyThrottle
from public_api.views.network import IsNetworkAdmin


class WebhookEndpointListView(APIView):
    permission_classes = [IsAuthenticated, IsNetworkAdmin]
    throttle_classes = [APIKeyThrottle]

    @extend_schema(summary='[Admin] List webhook endpoints')
    def get(self, request):
        qs = WebhookEndpoint.objects.filter(brand=request.brand)
        return Response(WebhookEndpointSerializer(qs, many=True).data)

    @extend_schema(request=WebhookEndpointSerializer, summary='[Admin] Create webhook endpoint')
    def post(self, request):
        ser = WebhookEndpointSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        endpoint = ser.save(brand=request.brand)
        return Response(WebhookEndpointSerializer(endpoint).data, status=status.HTTP_201_CREATED)


class WebhookEndpointDetailView(APIView):
    permission_classes = [IsAuthenticated, IsNetworkAdmin]
    throttle_classes = [APIKeyThrottle]

    def _get(self, request, pk):
        try:
            return WebhookEndpoint.objects.get(pk=pk, brand=request.brand)
        except WebhookEndpoint.DoesNotExist:
            return None

    @extend_schema(summary='[Admin] Retrieve webhook endpoint')
    def get(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(WebhookEndpointSerializer(obj).data)

    @extend_schema(summary='[Admin] Delete webhook endpoint')
    def delete(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WebhookDeliveryListView(APIView):
    permission_classes = [IsAuthenticated, IsNetworkAdmin]
    throttle_classes = [APIKeyThrottle]

    @extend_schema(summary='[Admin] List deliveries for a webhook endpoint')
    def get(self, request, pk):
        try:
            endpoint = WebhookEndpoint.objects.get(pk=pk, brand=request.brand)
        except WebhookEndpoint.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        deliveries = WebhookDelivery.objects.filter(endpoint=endpoint)[:200]
        return Response(WebhookDeliverySerializer(deliveries, many=True).data)
