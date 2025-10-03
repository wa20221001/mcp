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

"""AWS helper for the EKS MCP Server."""

import boto3
import os
from threading import RLock
from awslabs.eks_mcp_server import __version__
from botocore.config import Config
from loguru import logger
from typing import Any, Dict, Optional, Tuple


class AwsHelper:
    """Helper class for AWS operations.

    This class provides utility methods for interacting with AWS services,
    including region and profile management and client creation.

    This class implements a singleton pattern with a client cache to avoid
    creating multiple clients for the same service.
    """

    # Singleton instance
    _instance = None

    # Client cache keyed by (service_name, region, profile)
    _client_cache: Dict[Tuple[str, Optional[str], Optional[str]], Any] = {}

    # Active profile (overrides environment variable)
    _active_profile: Optional[str] = None

    # Re-entrant lock to guard shared state
    _lock: RLock = RLock()

    @staticmethod
    def get_aws_region() -> Optional[str]:
        """Get the AWS region from the environment if set."""
        return os.environ.get('AWS_REGION')

    @staticmethod
    def get_aws_profile() -> Optional[str]:
        """Get the AWS profile from the environment if set."""
        return os.environ.get('AWS_PROFILE')
    
    @classmethod
    def set_active_profile(cls, profile_name: Optional[str]) -> None:
        """Set the active AWS profile and clear the client cache.
        
        This allows dynamic switching between AWS profiles at runtime.
        Setting the profile clears all cached clients to ensure they
        are recreated with the new profile.
        
        Args:
            profile_name: Name of the AWS profile to set, or None to use default
        """
        with cls._lock:
            cls._active_profile = profile_name
            cls._client_cache.clear()
        logger.debug(f'Active AWS profile set to: {profile_name!r}')
    
    @classmethod
    def get_active_profile(cls) -> Optional[str]:
        """Get the currently active AWS profile.
        
        Returns the profile set via set_active_profile, or falls back to
        the AWS_PROFILE environment variable.
        
        Returns:
            Name of the active AWS profile, or None if using default credentials
        """
        with cls._lock:
            active_profile = cls._active_profile
        return active_profile if active_profile is not None else cls.get_aws_profile()

    @classmethod
    def create_boto3_client(cls, service_name: str, region_name: Optional[str] = None) -> Any:
        """Create or retrieve a cached boto3 client with the appropriate profile and region.

        The client is configured with a custom user agent suffix 'awslabs/mcp/eks-mcp-server/{version}'
        to identify API calls made by the EKS MCP Server. Clients are cached to improve performance
        and reduce resource usage.

        Args:
            service_name: The AWS service name (e.g., 'ec2', 's3', 'eks')
            region_name: Optional region name override

        Returns:
            A boto3 client for the specified service

        Raises:
            Exception: If there's an error creating the client
        """
        try:
            # Resolve region preference and active profile
            resolved_region: Optional[str] = (
                region_name if region_name is not None else cls.get_aws_region()
            )
            profile = cls.get_active_profile()

            cache_key = (service_name, resolved_region, profile)

            with cls._lock:
                cached_client = cls._client_cache.get(cache_key)
            if cached_client is not None:
                logger.debug(
                    'Using cached boto3 client for %s (region=%r, profile=%r)',
                    service_name,
                    resolved_region,
                    profile,
                )
                return cached_client

            # Create config with user agent suffix
            config = Config(user_agent_extra=f'awslabs/mcp/eks-mcp-server/{__version__}')

            session_kwargs: Dict[str, Optional[str]] = {}
            if profile is not None:
                session_kwargs['profile_name'] = profile
            if resolved_region is not None:
                session_kwargs['region_name'] = resolved_region

            session = boto3.Session(**session_kwargs)
            client_kwargs: Dict[str, Any] = {'config': config}
            if resolved_region is not None:
                client_kwargs['region_name'] = resolved_region

            client = session.client(service_name, **client_kwargs)

            with cls._lock:
                cls._client_cache[cache_key] = client

            return client
        except Exception as e:
            # Re-raise with more context
            raise Exception(f'Failed to create boto3 client for {service_name}: {str(e)}')
