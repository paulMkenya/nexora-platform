"""
Network admin API — read/write access to all brand-scoped resources.
All endpoints require NETWORK_ADMIN role or superuser.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from offer.models import Advertiser, Offer
from public_api.serializers import (
    AdminAdvertiserSerializer,
    AdminConversionSerializer,
    AdminOfferSerializer,
)
from public_api.throttling import APIKeyThrottle
from tracker.models import Conversion
from user_profile.models import Profile


class IsNetworkAdmin(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        profile = getattr(request.user, 'profile', None)
        return profile is not None and profile.role == Profile.Role.NETWORK_ADMIN


class AdminOfferListView(APIView):
    permission_classes = [IsAuthenticated, IsNetworkAdmin]
    throttle_classes = [APIKeyThrottle]

    @extend_schema(summary='[Admin] List all offers for brand')
    def get(self, request):
        qs = Offer.objects.filter(brand=request.brand)
        return Response(AdminOfferSerializer(qs, many=True).data)

    @extend_schema(request=AdminOfferSerializer, summary='[Admin] Create offer')
    def post(self, request):
        ser = AdminOfferSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        offer = ser.save(brand=request.brand)
        return Response(AdminOfferSerializer(offer).data, status=status.HTTP_201_CREATED)


class AdminOfferDetailView(APIView):
    permission_classes = [IsAuthenticated, IsNetworkAdmin]
    throttle_classes = [APIKeyThrottle]

    def _get(self, request, pk):
        try:
            return Offer.objects.get(pk=pk, brand=request.brand)
        except Offer.DoesNotExist:
            return None

    @extend_schema(summary='[Admin] Retrieve offer')
    def get(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(AdminOfferSerializer(obj).data)

    @extend_schema(request=AdminOfferSerializer, summary='[Admin] Update offer')
    def patch(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = AdminOfferSerializer(obj, data=request.data, partial=True)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        ser.save()
        return Response(ser.data)

    @extend_schema(summary='[Admin] Delete offer')
    def delete(self, request, pk):
        obj = self._get(request, pk)
        if obj is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminAdvertiserListView(APIView):
    permission_classes = [IsAuthenticated, IsNetworkAdmin]
    throttle_classes = [APIKeyThrottle]

    @extend_schema(summary='[Admin] List advertisers for brand')
    def get(self, request):
        qs = Advertiser.objects.filter(brand=request.brand)
        return Response(AdminAdvertiserSerializer(qs, many=True).data)


class AdminConversionListView(APIView):
    permission_classes = [IsAuthenticated, IsNetworkAdmin]
    throttle_classes = [APIKeyThrottle]

    @extend_schema(summary='[Admin] List conversions for brand')
    def get(self, request):
        qs = Conversion.objects.filter(brand=request.brand).order_by('-created_at')[:1000]
        return Response(AdminConversionSerializer(qs, many=True).data)
