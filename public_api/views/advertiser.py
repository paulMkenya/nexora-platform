"""
Advertiser-scoped API: offers, conversions, wallet.

All endpoints require the authenticated user to have an Advertiser profile.
Resources are scoped to request.brand AND the requesting advertiser.
"""
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from offer.models import Offer
from public_api.serializers import (
    AdvertiserConversionSerializer,
    AdvertiserOfferSerializer,
    BulkActionSerializer,
    WalletSerializer,
)
from public_api.throttling import APIKeyThrottle
from tracker.models import APPROVED_STATUS, REJECTED_STATUS, Conversion


def _get_advertiser(user):
    return getattr(user, 'advertiser_profile', None)


class IsAdvertiserPermission:
    def has_permission(self, request, view):
        return _get_advertiser(request.user) is not None


class AdvertiserOfferListView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIKeyThrottle]

    def _base_qs(self, request):
        adv = _get_advertiser(request.user)
        if adv is None:
            return Offer.objects.none()
        return Offer.objects.filter(brand=request.brand, advertiser=adv)

    @extend_schema(summary='List advertiser offers')
    def get(self, request):
        adv = _get_advertiser(request.user)
        if adv is None:
            return Response({'detail': 'No advertiser profile.'}, status=status.HTTP_403_FORBIDDEN)
        qs = self._base_qs(request)
        return Response(AdvertiserOfferSerializer(qs, many=True).data)

    @extend_schema(request=AdvertiserOfferSerializer, summary='Create an offer')
    def post(self, request):
        adv = _get_advertiser(request.user)
        if adv is None:
            return Response({'detail': 'No advertiser profile.'}, status=status.HTTP_403_FORBIDDEN)
        ser = AdvertiserOfferSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        offer = ser.save(brand=request.brand, advertiser=adv)
        return Response(AdvertiserOfferSerializer(offer).data, status=status.HTTP_201_CREATED)


class AdvertiserOfferDetailView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIKeyThrottle]

    def _get(self, request, pk):
        adv = _get_advertiser(request.user)
        if adv is None:
            return None
        try:
            return Offer.objects.get(pk=pk, brand=request.brand, advertiser=adv)
        except Offer.DoesNotExist:
            return None

    @extend_schema(summary='Retrieve an offer')
    def get(self, request, pk):
        offer = self._get(request, pk)
        if offer is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(AdvertiserOfferSerializer(offer).data)

    @extend_schema(request=AdvertiserOfferSerializer, summary='Update an offer')
    def patch(self, request, pk):
        offer = self._get(request, pk)
        if offer is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        ser = AdvertiserOfferSerializer(offer, data=request.data, partial=True)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        ser.save()
        return Response(ser.data)

    @extend_schema(summary='Delete an offer')
    def delete(self, request, pk):
        offer = self._get(request, pk)
        if offer is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        offer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdvertiserConversionListView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIKeyThrottle]

    def _base_qs(self, request):
        adv = _get_advertiser(request.user)
        if adv is None:
            return Conversion.objects.none()
        offer_ids = Offer.objects.filter(brand=request.brand, advertiser=adv).values_list('id', flat=True)
        return Conversion.objects.filter(brand=request.brand, offer_id__in=offer_ids)

    @extend_schema(summary='List conversions for advertiser')
    def get(self, request):
        adv = _get_advertiser(request.user)
        if adv is None:
            return Response({'detail': 'No advertiser profile.'}, status=status.HTTP_403_FORBIDDEN)
        qs = self._base_qs(request).order_by('-created_at')[:500]
        return Response(AdvertiserConversionSerializer(qs, many=True).data)


class AdvertiserConversionBulkApproveView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIKeyThrottle]

    @extend_schema(request=BulkActionSerializer, summary='Bulk approve conversions')
    def post(self, request):
        adv = _get_advertiser(request.user)
        if adv is None:
            return Response({'detail': 'No advertiser profile.'}, status=status.HTTP_403_FORBIDDEN)
        ser = BulkActionSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        offer_ids = Offer.objects.filter(brand=request.brand, advertiser=adv).values_list('id', flat=True)
        updated = Conversion.objects.filter(
            brand=request.brand, offer_id__in=offer_ids, id__in=ser.validated_data['ids'],
        ).update(status=APPROVED_STATUS, comment=ser.validated_data['comment'])
        return Response({'updated': updated})


class AdvertiserConversionBulkRejectView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIKeyThrottle]

    @extend_schema(request=BulkActionSerializer, summary='Bulk reject conversions')
    def post(self, request):
        adv = _get_advertiser(request.user)
        if adv is None:
            return Response({'detail': 'No advertiser profile.'}, status=status.HTTP_403_FORBIDDEN)
        ser = BulkActionSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        offer_ids = Offer.objects.filter(brand=request.brand, advertiser=adv).values_list('id', flat=True)
        updated = Conversion.objects.filter(
            brand=request.brand, offer_id__in=offer_ids, id__in=ser.validated_data['ids'],
        ).update(status=REJECTED_STATUS, comment=ser.validated_data['comment'])
        return Response({'updated': updated})


class AdvertiserWalletView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIKeyThrottle]

    @extend_schema(summary='Get advertiser wallet balance')
    def get(self, request):
        adv = _get_advertiser(request.user)
        if adv is None:
            return Response({'detail': 'No advertiser profile.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            wallet = adv.wallet
            data = WalletSerializer({
                'balance': wallet.balance,
                'currency': wallet.currency,
                'credit_limit': getattr(wallet, 'credit_limit', None),
            }).data
        except Exception:
            data = WalletSerializer({'balance': '0.00', 'currency': 'USD'}).data
        return Response(data)
