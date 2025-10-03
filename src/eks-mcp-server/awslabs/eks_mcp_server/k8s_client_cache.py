# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Kubernetes client cache for the EKS MCP Server."""

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Dict, Iterable, List, Optional, Tuple

import yaml
from awslabs.eks_mcp_server.aws_helper import AwsHelper
from awslabs.eks_mcp_server.k8s_apis import K8sApis
from cachetools import TTLCache
from loguru import logger


# Presigned url timeout in seconds
URL_TIMEOUT = 60
TOKEN_PREFIX = 'k8s-aws-v1.'
K8S_AWS_ID_HEADER = 'x-k8s-aws-id'

# 14 minutes in seconds (buffer before the 15-minute token expiration)
TOKEN_TTL = 14 * 60


class KubeconfigParseError(Exception):
    """Raised when kubeconfig parsing fails."""


@dataclass(frozen=True)
class KubeconfigIndex:
    """Indexed kubeconfig metadata for quick context lookup."""

    signature: Tuple[Tuple[str, int], ...]
    context_to_cluster: Dict[str, str]


class K8sClientCache:
    """Singleton class for managing Kubernetes API client cache.

    This class provides a centralized cache for Kubernetes API clients
    to avoid creating multiple clients for the same cluster.
    """

    # Singleton instance
    _instance = None
    _lock: RLock = RLock()

    def __new__(cls):
        """Ensure only one instance of K8sClientCache exists."""
        if cls._instance is None:
            cls._instance = super(K8sClientCache, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the K8s client cache."""
        # Only initialize once
        if hasattr(self, '_initialized') and self._initialized:
            return

        # Client cache with TTL to handle token expiration; keyed by (context, cluster)
        self._client_cache: TTLCache = TTLCache(maxsize=100, ttl=TOKEN_TTL)

        # Flag to track if STS event handlers have been registered
        self._sts_event_handlers_registered = False
        
        # Active Kubernetes context (for kubeconfig-based contexts)
        self._active_context: Optional[str] = None

        # Cached mapping of contexts to clusters with file signature tracking
        self._kubeconfig_index: Optional[KubeconfigIndex] = None

        self._initialized = True

    def _get_sts_client(self):
        """Get the STS client with event handlers registered."""
        sts_client = AwsHelper.create_boto3_client('sts')

        # Register STS event handlers only once
        if not self._sts_event_handlers_registered:
            sts_client.meta.events.register(
                'provide-client-params.sts.GetCallerIdentity',
                self._retrieve_k8s_aws_id,
            )
            sts_client.meta.events.register(
                'before-sign.sts.GetCallerIdentity',
                self._inject_k8s_aws_id_header,
            )
            self._sts_event_handlers_registered = True

        return sts_client

    def _retrieve_k8s_aws_id(self, params, context, **kwargs):
        """Retrieve the Kubernetes AWS ID from parameters."""
        if K8S_AWS_ID_HEADER in params:
            context[K8S_AWS_ID_HEADER] = params.pop(K8S_AWS_ID_HEADER)

    def _inject_k8s_aws_id_header(self, request, **kwargs):
        """Inject the Kubernetes AWS ID header into the request."""
        if K8S_AWS_ID_HEADER in request.context:
            request.headers[K8S_AWS_ID_HEADER] = request.context[K8S_AWS_ID_HEADER]

    def _get_cluster_credentials(self, cluster_name: str):
        """Get credentials for an EKS cluster (private method).

        Args:
            cluster_name: Name of the EKS cluster

        Returns:
            Tuple of (endpoint, token, ca_data)

        Raises:
            ValueError: If the cluster credentials are invalid
            Exception: If there's an error getting the cluster credentials
        """
        eks_client = AwsHelper.create_boto3_client('eks')
        sts_client = self._get_sts_client()

        # Get cluster details
        response = eks_client.describe_cluster(name=cluster_name)
        endpoint = response['cluster']['endpoint']
        ca_data = response['cluster']['certificateAuthority']['data']

        # Generate a presigned URL for authentication
        url = sts_client.generate_presigned_url(
            'get_caller_identity',
            Params={K8S_AWS_ID_HEADER: cluster_name},
            ExpiresIn=URL_TIMEOUT,
            HttpMethod='GET',
        )

        # Create the token from the presigned URL
        token = TOKEN_PREFIX + base64.urlsafe_b64encode(url.encode('utf-8')).decode(
            'utf-8'
        ).rstrip('=')

        return endpoint, token, ca_data

    def get_client(self, cluster_name: str) -> K8sApis:
        """Get a Kubernetes client for the specified cluster.

        This is the only public method to access K8s API clients.

        Args:
            cluster_name: Name of the EKS cluster

        Returns:
            K8sApis instance

        Raises:
            ValueError: If the cluster credentials are invalid
            Exception: If there's an error getting the cluster credentials
        """
        cache_key = (self._active_context, cluster_name)

        with self._lock:
            cached_client = self._client_cache.get(cache_key)
        if cached_client is not None:
            logger.debug(
                'Using cached Kubernetes client for cluster %s (context=%r)',
                cluster_name,
                self._active_context,
            )
            return cached_client

        try:
            # Create a new client
            endpoint, token, ca_data = self._get_cluster_credentials(cluster_name)

            # Validate credentials
            if not endpoint or not token or endpoint is None or token is None:
                raise ValueError('Invalid cluster credentials')

            new_client = K8sApis(endpoint, token, ca_data)
        except ValueError:
            # Re-raise ValueError for invalid credentials
            raise
        except Exception as e:
            # Re-raise any other exceptions
            raise Exception(f'Failed to get cluster credentials: {str(e)}')

        with self._lock:
            self._client_cache[cache_key] = new_client

        return new_client
    
    def set_active_context(self, context_name: str) -> None:
        """Set the active Kubernetes context.
        
        This allows dynamic switching between Kubernetes contexts at runtime.
        Setting the context clears the client cache to ensure clients are
        recreated with the new context.
        
        Args:
            context_name: Name of the Kubernetes context to set
        """
        with self._lock:
            self._active_context = context_name
            keys_to_remove = [key for key in self._client_cache if key[0] == context_name]
            for key in keys_to_remove:
                try:
                    del self._client_cache[key]
                except KeyError:
                    continue
        logger.debug(f'Active Kubernetes context set to: {context_name!r}')
    
    def get_active_context(self) -> Optional[str]:
        """Get the currently active Kubernetes context.
        
        Returns:
            Name of the active context, or None if not set
        """
        with self._lock:
            return self._active_context

    def list_contexts(self) -> List[str]:
        """List all known Kubernetes contexts from kubeconfig files."""
        with self._lock:
            index = self._ensure_kubeconfig_index()
            if index is None:
                return []
            return list(index.context_to_cluster.keys())
    
    def get_cluster_from_context(self, context_name: Optional[str] = None) -> Optional[str]:
        """Get the cluster name associated with a Kubernetes context.
        
        This reads the kubeconfig file to map a context to its cluster name.
        
        Args:
            context_name: Name of the context, or None to use the active context
            
        Returns:
            Cluster name associated with the context, or None if not found
        """
        target_context = context_name
        if target_context is None:
            with self._lock:
                target_context = self._active_context

        if target_context is None:
            return None

        with self._lock:
            index = self._ensure_kubeconfig_index()
            if index is None:
                return None
            cluster_name = index.context_to_cluster.get(target_context)

        if cluster_name:
            logger.debug(
                'Resolved context %s to cluster %s',
                target_context,
                cluster_name,
            )
            return cluster_name

        logger.warning(
            'Context %s not found in kubeconfig sources %s',
            target_context,
            self._kubeconfig_signature_repr(),
        )
        return None

    def _kubeconfig_signature_repr(self) -> str:
        with self._lock:
            if self._kubeconfig_index is None:
                return '[]'
            return str([path for path, _ in self._kubeconfig_index.signature])

    def _ensure_kubeconfig_index(self) -> Optional[KubeconfigIndex]:
        paths = self._resolve_kubeconfig_paths()
        signature = self._build_signature(paths)

        if self._kubeconfig_index is not None and self._kubeconfig_index.signature == signature:
            return self._kubeconfig_index

        context_map: Dict[str, str] = {}

        for path in paths:
            if not path.exists():
                logger.debug('Kubeconfig file %s does not exist; skipping', path)
                continue

            try:
                with path.open('r', encoding='utf-8') as handle:
                    kubeconfig = yaml.safe_load(handle) or {}
            except yaml.YAMLError as exc:
                raise KubeconfigParseError(str(exc)) from exc
            except OSError as exc:
                logger.warning('Unable to read kubeconfig %s: %s', path, exc)
                continue

            for context in kubeconfig.get('contexts', []) or []:
                if not isinstance(context, dict):
                    continue
                name = context.get('name')
                if not name:
                    continue
                cluster = (context.get('context') or {}).get('cluster')
                if cluster:
                    context_map[name] = cluster

        self._kubeconfig_index = KubeconfigIndex(signature=signature, context_to_cluster=context_map)
        return self._kubeconfig_index

    @staticmethod
    def _build_signature(paths: Iterable[Path]) -> Tuple[Tuple[str, int], ...]:
        signature_entries: List[Tuple[str, int]] = []
        for path in paths:
            try:
                mtime_ns = path.stat().st_mtime_ns
            except FileNotFoundError:
                mtime_ns = -1
            signature_entries.append((str(path), mtime_ns))
        return tuple(signature_entries)

    @staticmethod
    def _resolve_kubeconfig_paths() -> List[Path]:
        raw_value = os.environ.get('KUBECONFIG')
        if raw_value:
            parts = [Path(part).expanduser() for part in raw_value.split(os.pathsep) if part]
            if parts:
                return parts
        return [Path.home() / '.kube' / 'config']

