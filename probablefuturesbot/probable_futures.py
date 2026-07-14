import base64
import json
import logging
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)

AUTH_URL = "https://graphql.probablefutures.org/auth/token"
GRAPHQL_URL = "https://graphql.probablefutures.org/graphql"


class ProbableFutures:
    """Minimal client for the Probable Futures data API.

    Authentication uses the ``/auth/token`` endpoint with HTTP Basic auth
    (client id / client secret) and returns a short-lived (24h) Bearer token
    that is then used against the GraphQL endpoint.
    See https://docs.probablefutures.org/data-api-access/.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        auth_url: str = AUTH_URL,
        graphql_url: str = GRAPHQL_URL,
        timeout: int = 30,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url
        self.graphql_url = graphql_url
        self.timeout = timeout
        self._access_token = None

    def connect(self) -> None:
        encoded_credentials = base64.b64encode(
            (self.client_id + ":" + self.client_secret).encode()
        ).decode()
        response = requests.get(
            self.auth_url,
            headers={"Authorization": "Basic " + encoded_credentials},
            timeout=self.timeout,
        )
        response.raise_for_status()

        body = response.json()
        if "access_token" not in body:
            raise Exception(f"Failed to obtain access token from Probable Futures API: {body}")
        self._access_token = body["access_token"]

    @staticmethod
    def build_query(input_fields: Dict, output_fields: List[str]) -> str:
        # Numbers/null are emitted bare, strings are quoted and escaped -
        # json.dumps produces valid GraphQL scalar literals for all of these.
        input_str = ", ".join(f"{key}: {json.dumps(value)}" for key, value in input_fields.items())
        output_str = " ".join(output_fields)
        return (
            "mutation {"
            f" getDatasetStatistics(input: {{{input_str}}})"
            f" {{ datasetStatisticsResponses {{ {output_str} }} }}"
            " }"
        )

    def request(self, input_fields: Dict, output_fields: List[str]) -> requests.Response:
        if self._access_token is None:
            self.connect()

        query = {"query": self.build_query(input_fields, output_fields), "variables": {}}

        def post():
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self._access_token,
            }
            return requests.post(self.graphql_url, headers=headers, json=query, timeout=self.timeout)

        response = post()

        # The access token expires after 24 hours; transparently reconnect once.
        if response.status_code in (401, 403):
            logger.info("Probable Futures access token rejected, reconnecting.")
            self.connect()
            response = post()

        return response
