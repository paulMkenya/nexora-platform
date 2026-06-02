"""Brand-aware password-reset flow.

Reuses Django's battle-tested auth views; the customisation is making the reset
email carry the brand's name/support address, send through the brand's own SMTP
connection when configured, and use the brand's host (from the request) for the
link. Works for every account type — affiliate, brand admin, platform owner —
since they all share the auth User model.
"""
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import PasswordResetForm
from django.core.mail import EmailMultiAlternatives
from django.template import loader
from django.urls import reverse_lazy

from brands.email import connection_for_brand, from_email_for_brand


class BrandPasswordResetForm(PasswordResetForm):
    """PasswordResetForm that sends through a brand-specific connection."""

    connection = None

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        subject = ''.join(loader.render_to_string(subject_template_name, context).splitlines())
        body = loader.render_to_string(email_template_name, context)
        message = EmailMultiAlternatives(subject, body, from_email, [to_email],
                                         connection=self.connection)
        if html_email_template_name is not None:
            html = loader.render_to_string(html_email_template_name, context)
            message.attach_alternative(html, 'text/html')
        message.send()


class BrandPasswordResetView(auth_views.PasswordResetView):
    template_name = 'registration/password_reset_form.html'
    email_template_name = 'registration/password_reset_email.txt'
    subject_template_name = 'registration/password_reset_subject.txt'
    form_class = BrandPasswordResetForm
    success_url = reverse_lazy('affiliate_ui:password_reset_done')

    def dispatch(self, request, *args, **kwargs):
        brand = getattr(request, 'brand', None)
        self.extra_email_context = {
            'brand_name': brand.name if brand else 'Nexora',
            'support_email': (getattr(brand, 'support_email', '') or 'support@cloudtrade.pro'),
        }
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        brand = getattr(self.request, 'brand', None)
        form.connection = connection_for_brand(brand)
        self.from_email = from_email_for_brand(brand)
        return super().form_valid(form)


class BrandPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'registration/password_reset_confirm.html'
    success_url = reverse_lazy('affiliate_ui:password_reset_complete')


class BrandPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'registration/password_reset_done.html'


class BrandPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'registration/password_reset_complete.html'
