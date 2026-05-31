"""
OAuth2 client-credentials token endpoint and API key management.

Token endpoint flow:
  POST /api/v1/auth/token
  Content-Type: application/json
  {"grant_type": "client_credentials", "client_id": "<uuid>", "client_secret": "<secret>"}

  → {"access_token": "<jwt>", "token_type": "bearer", "expires_in": 3600}

The returned JWT is a standard simplejwt AccessToken carrying an extra 'api_key_id'
claim.  It can be used as a regular Bearer token on all subsequent API requests.
"""
from datetime import timedelta

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

from public_api.models import APIKey
from public_api.serializers import APIKeyCreateSerializer, APIKeyListSerializer, TokenRequestSerializer


class TokenView(APIView):
    permission_classes = []
    authentication_classes = []

    @extend_schema(
        request=TokenRequestSerializer,
        summary='OAuth2 client credentials token',
        description='Exchange API client_id + client_secret for a short-lived JWT Bearer token.',
    )
    def post(self, request):
        ser = TokenRequestSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        data = ser.validated_data
        try:
            api_key = APIKey.objects.select_related('user').get(
                client_id=data['client_id'],
                secret=data['client_secret'],
                is_active=True,
            )
        except APIKey.DoesNotExist:
            return Response({'error': 'invalid_client'}, status=status.HTTP_401_UNAUTHORIZED)

        token = AccessToken()
        token.set_exp(lifetime=timedelta(hours=1))
        token['user_id'] = api_key.user_id
        token['api_key_id'] = api_key.pk

        return Response({
            'access_token': str(token),
            'token_type': 'bearer',
            'expires_in': 3600,
        })


class APIKeyListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary='List your API keys')
    def get(self, request):
        keys = APIKey.objects.filter(user=request.user)
        return Response(APIKeyListSerializer(keys, many=True).data)

    @extend_schema(request=APIKeyCreateSerializer, summary='Create an API key')
    def post(self, request):
        ser = APIKeyCreateSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        key = APIKey.generate(
            user=request.user,
            name=ser.validated_data['name'],
            requests_per_hour=ser.validated_data.get('requests_per_hour', 1000),
        )
        return Response(APIKeyCreateSerializer(key).data, status=status.HTTP_201_CREATED)


class APIKeyDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_key(self, request, pk):
        try:
            return APIKey.objects.get(pk=pk, user=request.user)
        except APIKey.DoesNotExist:
            return None

    @extend_schema(summary='Deactivate an API key')
    def delete(self, request, pk):
        key = self._get_key(request, pk)
        if key is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        key.is_active = False
        key.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)
