"""Affiliate-facing API & Docs page — Affiliate Inbound API spec §6/§6.4.
Everything here reuses existing pieces rather than rebuilding them:
leadgen.api_doc.build_doc_context() (the single doc data source),
public_api.APIKey (the existing key model + generate/regenerate/revoke),
and WeasyPrint (already a dependency, already used the same way by
billing/tasks/invoice.py for a live-rendered-to-PDF document)."""
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from affiliate_ui.gates import require_approved_affiliate
from impersonation.decorators import block_when_impersonating
from leadgen.api_doc import build_doc_context
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

    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html, base_url=request.build_absolute_uri('/')).write_pdf()
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="nexora-affiliate-api-docs.pdf"'
    except Exception:
        # WeasyPrint unavailable (system libs missing, same fallback billing
        # uses) — serve the HTML directly rather than a 500.
        response = HttpResponse(html, content_type='text/html')
    return response


@require_approved_affiliate
def api_docs_text(request):
    doc = build_doc_context(request, request.user)
    lines = [
        'NEXORA AFFILIATE INBOUND API', '=' * 29, '',
        f'Base URL: {doc["base_url"]}', '',
        'ENDPOINTS',
    ]
    for ep in doc['endpoints']:
        lines.append(f'  {ep["method"]:6s} {doc["base_url"]}{ep["path"]} — {ep["purpose"]}')
    lines += ['', 'AUTH', '  Header: Authorization: ApiKey YOUR_API_KEY_HERE']
    if doc['keys']:
        lines.append('  Your keys:')
        for k in doc['keys']:
            lines.append(f'    {k["name"]} ({k["client_id"]}) — {k["requests_per_hour"]}/hour')
    lines += ['', 'SUBMIT FIELDS']
    for f in doc['fields']:
        req = 'required' if f['required'] else 'optional'
        lines.append(f'  {f["name"]} ({req}, {f["type"]}){": " + f["help_text"] if f["help_text"] else ""}')
    lines += ['', 'YOUR AVAILABLE OFFERS']
    for o in doc['offers']:
        lines.append(f'  offer_id={o["id"]}: {o["title"]}')
    lines += ['', 'CANONICAL STATUSES']
    for s in doc['statuses']:
        lines.append(f'  {s["value"]} — {s["label"]}')
    lines += [
        '', 'TESTING -> LIVE',
        '  Every offer starts in TESTING: Nexora sets your leads\' statuses manually so you can',
        '  confirm your own source receives them correctly. Once confirmed, the offer goes LIVE',
        '  and the buyer\'s own reported status flows to you verbatim.',
        '', 'POSTBACKS (push)',
        '  Macros: ' + ' '.join('{' + m + '}' for m in doc['postback_macros']),
        '  Signed: X-Nexora-Signature: sha256=<hmac over the raw JSON body, your postback secret>',
        '  Carries a per-lead status_seq — ignore a delivery whose seq is lower than one you already saw.',
    ]
    for c in doc['postback_configs']:
        lines.append(f'  Configured: {c["url"]} (statuses: {", ".join(c["subscribed_statuses"])})')
    lines += [
        '', 'PULL (safety net)',
        f'  GET {doc["base_url"]}/api/leads?updated_since=<ISO datetime>',
        '', 'FULL API REFERENCE (OpenAPI)',
        f'  Interactive: {doc["openapi_swagger_url"]}',
        f'  Raw schema: {doc["openapi_schema_url"]}',
    ]
    response = HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')
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
