from odoo import models, api, _
import requests
import logging

_logger = logging.getLogger(__name__)

class PosSession(models.Model):
    _inherit = "pos.session"

    def _load_pos_data_fields(self, config_id):
        """Load additional Bonat fields for POS data in Odoo 19."""
        result = super()._load_pos_data_fields(config_id)
        return result

    @api.model
    def pos_reward_redeem(self, redeem_data):
        """
        Handles the API call from POS for Bonat reward redemption.
        Validates the coupon and checks if it has already been used.
        """
        _logger.info(f"Received Bonat Redeem Request redeem_data: {redeem_data}")

        # Extract data from the redeem_data
        required_fields = ["reward_code", "merchant_id", "branch_id", "date", "timestamp"]
        missing_fields = [field for field in required_fields if not redeem_data.get(field)]
        if missing_fields:
            _logger.error(f"Missing required fields in the request: {missing_fields}")
            return {
                "success": False,
                "error": f"Missing required fields: {', '.join(missing_fields)}",
            }

        reward_code = redeem_data.get("reward_code")
        merchant_id = redeem_data.get("merchant_id")
        branch_id = redeem_data.get("branch_id")
        date = redeem_data.get("date")
        timestamp = redeem_data.get("timestamp")

        # Check Bonat integration configuration
        company = self.env.company
        if not company.enable_bonat_integration:
            _logger.warning("Bonat integration is not enabled.")
            return {"success": False, "error": "Bonat integration is not enabled."}
        if not company.bonat_api_key:
            _logger.warning("Bonat API key is missing.")
            return {"success": False, "error": "Bonat API key is missing."}

        # Prepare API request
        api_url = "https://api.bonat.io/odoo_partner/redeem"
        # api_url = "https://stg-api.bonat.io/odoo_partner/redeem"
        headers = {
            "Authorization": f"Bearer {company.bonat_api_key}",
            "Content-Type": "application/json",
        }
        bonat_redeem_data = {
            "reward_code": reward_code,
            "merchant_id": merchant_id,
            "branch_id": branch_id,
            "date": date,
            "timestamp": timestamp,
        }

        # Log the API redeem_data
        _logger.info(f"Sending request to Bonat API: {api_url}")
        _logger.debug(f"Request Headers: {headers}")
        _logger.debug(f"Request redeem_data: {bonat_redeem_data}")

        try:
            # Make the API call
            response = requests.post(api_url, json=bonat_redeem_data, headers=headers, timeout=10)
            # Check response status
            if response.status_code == 200:
                data = response.json()
                _logger.info(f"Bonat API Response reward redeem: {data}")
                if data.get("code") == 0:  # Success response
                    return {"success": True, "data": data.get("data")}
                else:
                    error_message = data.get("errors", "Invalid reward code.")
                    _logger.warning(f"Bonat API returned an error: {error_message}")
                    return {"success": False, "error": error_message}
            else:
                _logger.error(f"Bonat API Error: {response.text}")
                return {"success": False, "error": f"API Error: {response.status_code} - {response.reason}"}

        except requests.exceptions.RequestException as e:
            _logger.error(f"Request Exception in Bonat API call: {str(e)}")
            return {"success": False, "error": f"Request error: {str(e)}"}

        except Exception as e:
            _logger.exception("Unexpected error in Bonat reward redemption.")
            return {"success": False, "error": f"Unexpected server error: {str(e)}"}

    @api.model
    def pos_order_creation_request(self, order_creation_data):

        # Check company configuration
        company = self.env.company
        if not company.enable_bonat_integration or not company.bonat_api_key:
            return {"success": False, "error": "Bonat integration is not enabled or API key is missing."}

        api_url = "https://api.bonat.io/odoo_partner/order"
        # api_url = "https://stg-api.bonat.io/odoo_partner/order"
        headers = {
            "Authorization": f"Bearer {company.bonat_api_key}",
            "Content-Type": "application/json",
        }

        try:
            _logger.info(f"POS Order Data: {order_creation_data}")
            response = requests.post(api_url, json=order_creation_data, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 0:  # Success response from Bonat
                    return {"success": True, "data": data.get("data")}
                else:
                    return {"success": False, "error": data.get("errors", "Invalid code.")}
            else:
                return {"success": False, "error": f"API Error: {response.text}"}
        except requests.exceptions.RequestException as e:
            _logger.error(f"Bonat API Request Exception: {str(e)}")
            return {"success": False}


class ResCompanyPosData(models.Model):
    _inherit = "res.company"

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Load Bonat-specific fields for res.company in POS."""
        result = super()._load_pos_data_fields(config_id)
        result += ["enable_bonat_integration", "bonat_api_key", "bonat_merchant_id", "bonat_merchant_name"]
        return result
