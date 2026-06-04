import django_filters
from rest_framework import generics
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from countries_plus.models import Country
from brands.links import affiliate_click_link
from offer.models import (
    Offer,
    Category,
    Currency,
    Goal,
    TrafficSource,
    OfferTrafficSource,
    Payout
)
from ..filters import CommaSeparatedTextFilter


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = (
            'iso',
        )


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = (
            'name',
        )


class TrafficSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrafficSource
        fields = (
            'name',
        )


class OfferTrafficSourceSerializer(serializers.ModelSerializer):
    name = serializers.SlugRelatedField(
        source='traffic_source',
        many=False, read_only=True, slug_field='name'
    )

    class Meta:
        model = OfferTrafficSource
        fields = (
            'name',
            'allowed'
        )


class GoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Goal
        fields = (
            'name',
        )


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = (
            'code',
            'name',
        )


class PayoutSerializer(serializers.ModelSerializer):
    countries = CountrySerializer(many=True, read_only=True)
    goal = GoalSerializer(read_only=True)
    currency = CurrencySerializer(read_only=True)

    class Meta:
        model = Payout
        fields = (
            'payout',
            'countries',
            'type',
            'currency',
            'goal',
        )


class OfferSerializer(serializers.ModelSerializer):
    countries = CountrySerializer(many=True, read_only=True)
    categories = CategorySerializer(many=True, read_only=True)
    traffic_sources = OfferTrafficSourceSerializer(
        source='offertrafficsource_set', many=True, read_only=True)
    payouts = PayoutSerializer(many=True, read_only=True)

    class Meta:
        model = Offer
        fields = (
            'id',
            'title',
            'description',
            'description_html',
            'preview_link',
            'icon',
            'countries',
            'categories',
            'traffic_sources',
            'payouts',
        )


class OfferFilterSet(django_filters.FilterSet):
    categories = CommaSeparatedTextFilter(
        field_name='categories',
        help_text='Exact category name or comma-separated names list'
    )
    countries = CommaSeparatedTextFilter(
        field_name='countries',
        help_text='Country 2-character code or comma-separated list'
    )


class OfferListView(generics.ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = OfferSerializer
    queryset = Offer.objects
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    filterset_class = OfferFilterSet
    search_fields = ['=id', 'title']
    ordering_fields = ['id', 'title']


class OfferRetrieveView(generics.RetrieveAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = OfferSerializer
    queryset = Offer.objects


class TrackingLinkView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, pk):
        user_id = request.user.id
        # Resolve the offer so the link is built from the OFFER's brand tracking
        # domain (white-label isolation), not the global platform domain.
        offer = Offer.objects.filter(pk=pk).first()
        if offer is None:
            return Response({'detail': 'Not found.'}, status=404)

        url = affiliate_click_link(offer, user_id, request=request)
        return Response({'url': url})

        # if offer.access == ACCESS_TYPE_PUBLIC:
        #     url = generate_tracking_link(offer_id, user_id)
        #     return Response({'url': url})

        # if offer.access == ACCESS_TYPE_PREMODERATION:
        #     approved = (
        #         Approval.objects
        #         .filter(
        #             offer_id=offer_id,
        #             affiliate_id=user_id,
        #             status=APPROVAL_STATUS_APPROVED)
        #         .exists())
        #     if approved:
        #         url = generate_tracking_link(offer_id, user_id)
        #         return Response({'url': url})
        #     else:
        #         return Response(status=status.HTTP_403_FORBIDDEN)
