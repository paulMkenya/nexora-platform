"""Affiliate-facing API & Docs page — Affiliate Inbound API spec §6/§6.4.
Everything here reuses existing pieces rather than rebuilding them:
leadgen.api_doc.build_doc_context() (the single doc data source),
public_api.APIKey (the existing key model + generate/regenerate/revoke),
and WeasyPrint (already a dependency, already used the same way by
billing/tasks/invoice.py for a live-rendered-to-PDF document)."""
import textwrap

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from impersonation.decorators import block_when_impersonating
from leadgen.api_doc import build_doc_context, build_public_doc_context
from public_api.models import APIKey


@require_approved_affiliate
def api_docs(request):
    return render(request, 'affiliate_ui/api_docs.html', {
        'doc': build_doc_context(request, request.user),
    })


@require_approved_affiliate
def api_docs_pdf(request):
    doc = build_doc_context(request, request.user)
    html = render_to_string('affiliate_ui/api_docs_pdf.html', {'doc': doc})
    return _render_pdf(html, base_url=request.build_absolute_uri('/'),
                       filename='nexora-affiliate-api-docs.pdf')


def _render_pdf(html, *, base_url, filename):
    """WeasyPrint the given HTML, falling back to serving the HTML itself if the
    system pango libraries are missing — the same fallback billing uses. Shared
    by the affiliate and public PDF views so the fallback cannot drift between
    them (it silently served HTML-named-.pdf for months once already)."""
    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html, base_url=base_url).write_pdf()
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception:
        return HttpResponse(html, content_type='text/html')


# --- Public, UNAUTHENTICATED documentation -----------------------------------
#
# Same contract, same derived source, none of the tenant-specific data — see
# leadgen.api_doc.build_public_doc_context for exactly what is withheld and why.
# This exists so an integration doc can be linked in an email or embedded in a
# proposal without the recipient needing an account, which is the normal way a
# traffic source's developers get it.
#
# Brand comes from the HOST here, and that is correct for this view in a way it
# was NOT correct for lead intake: there is no affiliate to key off, the page is
# served on the brand's own domain, and the worst case of the BrandMiddleware
# fallback is showing the default brand's PUBLIC contract — no tenant data can
# cross, because none is in the context at all.

def public_api_docs(request):
    return render(request, 'affiliate_ui/api_docs_public.html', {
        'doc': build_public_doc_context(request, getattr(request, 'brand', None)),
    })


def public_api_docs_pdf(request):
    doc = build_public_doc_context(request, getattr(request, 'brand', None))
    html = render_to_string('affiliate_ui/api_docs_pdf.html', {'doc': doc})
    return _render_pdf(html, base_url=request.build_absolute_uri('/'),
                       filename='nexora-inbound-lead-api.pdf')


def public_api_docs_text(request):
    doc = build_public_doc_context(request, getattr(request, 'brand', None))
    response = HttpResponse(_doc_as_text(doc), content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'inline; filename="nexora-inbound-lead-api.txt"'
    return response


def _wrap(paragraphs, indent='  '):
    """Narrative paragraphs as indented, wrapped lines. The words come from
    api_doc.NARRATIVE — the same ones HTML and PDF render — so this format can
    differ in layout but never in what it claims."""
    lines = []
    for para in paragraphs:
        lines.extend(textwrap.wrap(para, width=96, initial_indent=indent, subsequent_indent=indent))
        lines.append('')
    return lines


def _block(code):
    """A fenced example, indented into the surrounding text flow."""
    return [f'  {line}' for line in code.splitlines()]


def _text_header(doc):
    # "Prepared for: <affiliate>" is the one line that assumes a reader we know.
    # The public variant names the network instead, so the document still says
    # whose API it describes without inventing an addressee.
    if doc.get('public'):
        addressed = f'Network:      {doc["brand_name"]}' if doc.get('brand_name') else None
    else:
        addressed = f'Prepared for: {doc["affiliate_name"]}'
    lines = ['NEXORA AFFILIATE INBOUND API', '=' * 29, '']
    if addressed:
        lines.append(addressed)
    lines += [f'Base URL:     {doc["base_url"]}', '', 'ENDPOINTS']
    lines += [f'  {ep["method"]:6s} {doc["base_url"]}{ep["path"]} — {ep["purpose"]}'
              for ep in doc['endpoints']]
    return lines


def _text_auth(doc):
    lines = ['', 'AUTH', f'  {doc["auth_header"]}', '']
    lines += _wrap(doc['narrative']['auth'])
    if doc['keys']:
        lines.append('  Your keys:')
        lines += [f'    {k["name"]} ({k["client_id"]}) — {k["requests_per_hour"]}/hour'
                  for k in doc['keys']]
        lines.append('')
    return lines


def _text_fields_and_offers(doc):
    lines = ['SUBMIT FIELDS']
    for f in doc['fields']:
        req = 'required' if f['required'] else 'optional'
        lines.append(f'  {f["name"]} ({req}, {f["type"]}){": " + f["help_text"] if f["help_text"] else ""}')

    lines += ['', 'ATTRIBUTION — WHERE THE LEAD CAME FROM', '']
    lines += _wrap(doc['narrative']['attribution'])

    if doc.get('public'):
        lines += ['OFFERS']
        lines.append('  Your account manager gives you the offer_id(s) you are approved to send')
        lines.append('  to; they are also listed on your partner dashboard once your account is')
        lines.append('  open. Submitting an offer_id you are not approved for returns 400.')
        if doc.get('conditional_required_fields'):
            extra = ', '.join(doc['conditional_required_fields'])
            lines.append('')
            lines.append(f'  NOTE: some offers additionally require: {extra} — on top of the fields')
            lines.append('  marked required above, because the buyer they route to rejects a lead')
            lines.append('  without them. Submitting without one returns 400 naming the field.')
    else:
        lines += ['YOUR OFFERS']
        if doc['offers']:
            for o in doc['offers']:
                started = '' if o['started'] else ' (not started yet)'
                lines.append(f'  offer_id={o["id"]}: {o["title"]} — {o["phase_label"]}{started}')
                if o['required_fields']:
                    # On top of the fields already marked required in the table
                    # above — this offer's buyer rejects a lead without them.
                    lines.append(f'      also required: {", ".join(o["required_fields"])}')
        else:
            lines.append('  No offers assigned yet — contact your manager. Until an offer is assigned')
            lines.append('  to you, submissions will be rejected with "offer_id does not resolve to an')
            lines.append('  offer you can send to".')

    lines += ['', 'TESTING -> LIVE', '']
    lines += _wrap(doc['narrative']['testing_live'])
    lines += ['EXAMPLE REQUEST (SINGLE LEAD)', ''] + _block(doc['examples']['single_curl'])
    lines += ['', 'EXAMPLE REQUEST (BATCH)', ''] + _block(doc['examples']['batch_curl'])
    lines += ['', 'CANONICAL STATUSES']
    lines += [f'  {s["value"]} — {s["label"]}' for s in doc['statuses']]
    return lines


def _text_delivery(doc):
    lines = ['', 'POSTBACKS (push)', '',
             '  Macros: ' + ' '.join('{' + m + '}' for m in doc['postback_macros']), '']
    lines += _wrap(doc['narrative']['postbacks'])
    if not doc.get('public'):
        # The HTML/PDF render this as a link; a text export has to spell it out.
        lines += [f'  Manage them at {doc["base_url"]}/partner/postbacks/', '']
    if doc['postback_configs']:
        lines += [f'  Configured: {c["url"]} (statuses: {", ".join(c["subscribed_statuses"])})'
                  for c in doc['postback_configs']]
        lines.append('')

    lines += ['CONVERSIONS (FTD / DEPOSITS)', '']
    lines += _wrap(doc['narrative']['conversions'])

    lines += ['PULL (safety net)', '']
    lines += _wrap(doc['narrative']['pull'])
    lines += _block(doc['examples']['pull_curl'])
    lines += ['', '  Query parameters:']
    for f in doc['pull_filters']:
        lines.append(f'    {f["name"]}={f["example"]}')
        lines.extend(textwrap.wrap(
            f['purpose'], width=92, initial_indent=' ' * 8, subsequent_indent=' ' * 8))
    lines.append('')
    lines += ['', 'RATE LIMITS', '']
    lines += _wrap(doc['narrative']['rate_limits'])
    return lines


def _text_errors(doc):
    lines = ['ERRORS']
    for e in doc['errors']:
        lines.append(f'  {e["status"]} — {e["when"]}')
        lines.append(f'        {e["body"]}')
    if not doc.get('public'):
        # Withheld from the public doc — see the matching comment in
        # _api_docs_content.html. That schema maps the whole platform
        # (admin, network, advertiser wallet, webhooks), not this contract.
        lines += [
            '', 'FULL API REFERENCE (OpenAPI)',
            f'  Interactive: {doc["openapi_swagger_url"]}',
            f'  Raw schema: {doc["openapi_schema_url"]}',
        ]
    return lines


def _doc_as_text(doc):
    """The whole doc as plain text. One composer for both the affiliate and the
    public variant — the section builders already branch on doc['public'], so
    duplicating this list was the obvious way for the two to drift."""
    return '\n'.join(
        _text_header(doc) + _text_auth(doc) + _text_fields_and_offers(doc)
        + _text_delivery(doc) + _text_errors(doc)
    )


@require_approved_affiliate
def api_docs_text(request):
    doc = build_doc_context(request, request.user)
    response = HttpResponse(_doc_as_text(doc), content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="nexora-affiliate-api-docs.txt"'
    return response


@require_approved_affiliate
def api_keys(request):
    keys = APIKey.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'affiliate_ui/api_keys.html', {'keys': keys})


@block_when_impersonating
@require_approved_affiliate
@require_POST
def api_key_create(request):
    name = (request.POST.get('name') or '').strip()
    if not name:
        messages.error(request, 'Give the key a name.')
        return redirect('affiliate_ui:api_keys')
    key = APIKey.generate(user=request.user, name=name)
    messages.success(
        request,
        f'Key "{key.name}" created. Secret (shown once — copy it now): <code>{key.secret}</code>')
    return redirect('affiliate_ui:api_keys')


@block_when_impersonating
@require_approved_affiliate
@require_POST
def api_key_regenerate(request, pk):
    key = get_object_or_404(APIKey, pk=pk, user=request.user)
    new_secret = key.regenerate_secret()
    messages.success(
        request,
        f'Key "{key.name}" regenerated. New secret (shown once — copy it now): <code>{new_secret}</code> '
        f'— anything still using the old secret will stop working immediately.')
    return redirect('affiliate_ui:api_keys')


@block_when_impersonating
@require_approved_affiliate
@require_POST
def api_key_revoke(request, pk):
    key = get_object_or_404(APIKey, pk=pk, user=request.user)
    key.is_active = False
    key.save(update_fields=['is_active'])
    messages.success(request, f'Key "{key.name}" revoked.')
    return redirect('affiliate_ui:api_keys')
