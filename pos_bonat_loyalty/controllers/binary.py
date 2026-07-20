# -*- coding: utf-8 -*-
from odoo import http
from odoo.addons.web.controllers.binary import Binary
from odoo.http import request
from odoo.exceptions import UserError
from odoo.tools.image import image_guess_size_from_field_name


class WebsiteBinary(Binary):

    @http.route([
        '/api/image/<string:model>/<int:id>/<string:field>'
    ], type='http', auth="public")
    def api_content_image(self, model='ir.attachment', id=None, field='raw', access_token=None):
        try:
            record = request.env['ir.binary'].sudo()._find_record(None, model, id and int(id), access_token)
            stream = request.env['ir.binary']._get_image_stream_from(record, field)
        except UserError as exc:
            width, height = image_guess_size_from_field_name(field)
            # Use the ratio of the requested field_name instead of "raw"
            record = request.env.ref('web.image_placeholder').sudo()
            stream = request.env['ir.binary']._get_image_stream_from(
                record, 'raw'
            )

        res = stream.get_response()
        res.headers['Content-Security-Policy'] = "default-src 'none'"
        return res
