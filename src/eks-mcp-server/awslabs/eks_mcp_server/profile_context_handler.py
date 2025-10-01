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

"""Profile and context management handler for the EKS MCP Server."""

import os
from configparser import ConfigParser
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from awslabs.eks_mcp_server.aws_helper import AwsHelper
from awslabs.eks_mcp_server.k8s_client_cache import K8sClientCache
from awslabs.eks_mcp_server.logging_helper import LogLevel, log_with_request_id
from loguru import logger
from mcp.server.fastmcp import Context
from pydantic import Field


class ProfileContextHandler:
    """Handler for AWS profile and Kubernetes context management.
    
    This class provides tools for dynamically switching AWS profiles and
    Kubernetes contexts without requiring server restart.
    """

    def __init__(self, mcp):
        """Initialize the profile and context handler.
        
        Args:
            mcp: The MCP server instance
        """
        self.mcp = mcp
        
        # Register tools
        self.mcp.tool(name='set_aws_profile')(self.set_aws_profile)
        self.mcp.tool(name='get_aws_profile')(self.get_aws_profile)
        self.mcp.tool(name='list_aws_profiles')(self.list_aws_profiles)
        self.mcp.tool(name='set_k8s_context')(self.set_k8s_context)
        self.mcp.tool(name='get_k8s_context')(self.get_k8s_context)
        self.mcp.tool(name='list_k8s_contexts')(self.list_k8s_contexts)

    async def set_aws_profile(
        self,
        ctx: Context,
        profile_name: str = Field(
            ...,
            description='Name of the AWS profile to set as active. Must exist in ~/.aws/config or ~/.aws/credentials.',
        ),
    ) -> str:
        """Set the active AWS profile for subsequent operations.
        
        This tool allows you to dynamically switch between AWS profiles without
        restarting the MCP server. The profile change affects all subsequent
        AWS API calls until changed again.
        
        Args:
            ctx: MCP context
            profile_name: Name of the AWS profile to activate
            
        Returns:
            Success message with the active profile name
        """
        log_with_request_id(ctx, LogLevel.INFO, f'Setting AWS profile to: {profile_name}')
        
        try:
            # Validate that the profile exists
            available_profiles = self._get_aws_profiles()
            if profile_name not in available_profiles:
                raise ValueError(
                    f"Profile '{profile_name}' not found. Available profiles: {', '.join(available_profiles)}"
                )
            
            # Set the profile
            AwsHelper.set_active_profile(profile_name)
            
            log_with_request_id(
                ctx,
                LogLevel.INFO,
                f'Successfully set AWS profile to: {profile_name}',
            )
            
            return f"AWS profile successfully set to '{profile_name}'. All subsequent AWS operations will use this profile."
            
        except Exception as e:
            error_msg = f'Failed to set AWS profile: {str(e)}'
            log_with_request_id(ctx, LogLevel.ERROR, error_msg)
            raise Exception(error_msg)

    async def get_aws_profile(self, ctx: Context) -> str:
        """Get the currently active AWS profile.
        
        Returns the name of the AWS profile currently being used for AWS API calls.
        If no profile is explicitly set, returns information about the default profile.
        
        Args:
            ctx: MCP context
            
        Returns:
            Name of the current AWS profile or default credential source
        """
        
        log_with_request_id(ctx, LogLevel.INFO, 'Getting current AWS profile')
        
        try:
            current_profile = AwsHelper.get_active_profile()
            
            if current_profile:
                return f"Current AWS profile: '{current_profile}'"
            else:
                return "No AWS profile explicitly set. Using default AWS credential chain (environment variables, instance profile, etc.)."
                
        except Exception as e:
            error_msg = f'Failed to get AWS profile: {str(e)}'
            log_with_request_id(ctx, LogLevel.ERROR, error_msg)
            raise Exception(error_msg)

    async def list_aws_profiles(self, ctx: Context) -> Dict[str, List[str]]:
        """List all available AWS profiles from configuration files.
        
        Reads AWS profiles from ~/.aws/config and ~/.aws/credentials and returns
        a list of all available profile names that can be used with set_aws_profile.
        
        Args:
            ctx: MCP context
            
        Returns:
            Dictionary containing list of available AWS profiles
        """
        
        log_with_request_id(ctx, LogLevel.INFO, 'Listing available AWS profiles')
        
        try:
            profiles = self._get_aws_profiles()
            
            log_with_request_id(
                ctx,
                LogLevel.INFO,
                f'Found {len(profiles)} AWS profiles',
            )
            
            return {
                'profiles': sorted(profiles),
                'message': f'Found {len(profiles)} AWS profile(s). Use set_aws_profile to switch between them.',
            }
            
        except Exception as e:
            error_msg = f'Failed to list AWS profiles: {str(e)}'
            log_with_request_id(ctx, LogLevel.ERROR, error_msg)
            raise Exception(error_msg)

    async def set_k8s_context(
        self,
        ctx: Context,
        context_name: str = Field(
            ...,
            description='Name of the Kubernetes context to set as active. Must exist in ~/.kube/config.',
        ),
    ) -> str:
        """Set the active Kubernetes context for subsequent operations.
        
        This tool allows you to dynamically switch between Kubernetes contexts
        without restarting the MCP server. The context change affects all subsequent
        Kubernetes API calls that don't explicitly specify a cluster name.
        
        Args:
            ctx: MCP context
            context_name: Name of the Kubernetes context to activate
            
        Returns:
            Success message with the active context name
        """
        
        log_with_request_id(ctx, LogLevel.INFO, f'Setting Kubernetes context to: {context_name}')
        
        try:
            # Validate that the context exists
            available_contexts = self._get_k8s_contexts()
            if context_name not in available_contexts:
                raise ValueError(
                    f"Context '{context_name}' not found. Available contexts: {', '.join(available_contexts)}"
                )
            
            # Set the context in the client cache
            client_cache = K8sClientCache()
            client_cache.set_active_context(context_name)
            
            log_with_request_id(
                ctx,
                LogLevel.INFO,
                f'Successfully set Kubernetes context to: {context_name}',
            )
            
            return f"Kubernetes context successfully set to '{context_name}'. All subsequent Kubernetes operations will use this context."
            
        except Exception as e:
            error_msg = f'Failed to set Kubernetes context: {str(e)}'
            log_with_request_id(ctx, LogLevel.ERROR, error_msg)
            raise Exception(error_msg)

    async def get_k8s_context(self, ctx: Context) -> str:
        """Get the currently active Kubernetes context.
        
        Returns the name of the Kubernetes context currently being used for
        Kubernetes API calls.
        
        Args:
            ctx: MCP context
            
        Returns:
            Name of the current Kubernetes context
        """
        
        log_with_request_id(ctx, LogLevel.INFO, 'Getting current Kubernetes context')
        
        try:
            client_cache = K8sClientCache()
            current_context = client_cache.get_active_context()
            
            if current_context:
                return f"Current Kubernetes context: '{current_context}'"
            else:
                return "No Kubernetes context explicitly set. Operations require explicit cluster name."
                
        except Exception as e:
            error_msg = f'Failed to get Kubernetes context: {str(e)}'
            log_with_request_id(ctx, LogLevel.ERROR, error_msg)
            raise Exception(error_msg)

    async def list_k8s_contexts(self, ctx: Context) -> Dict[str, List[str]]:
        """List all available Kubernetes contexts from kubeconfig.
        
        Reads Kubernetes contexts from ~/.kube/config and returns a list of all
        available context names that can be used with set_k8s_context.
        
        Args:
            ctx: MCP context
            
        Returns:
            Dictionary containing list of available Kubernetes contexts
        """
        
        log_with_request_id(ctx, LogLevel.INFO, 'Listing available Kubernetes contexts')
        
        try:
            contexts = self._get_k8s_contexts()
            
            log_with_request_id(
                ctx,
                LogLevel.INFO,
                f'Found {len(contexts)} Kubernetes contexts',
            )
            
            return {
                'contexts': sorted(contexts),
                'message': f'Found {len(contexts)} Kubernetes context(s). Use set_k8s_context to switch between them.',
            }
            
        except Exception as e:
            error_msg = f'Failed to list Kubernetes contexts: {str(e)}'
            log_with_request_id(ctx, LogLevel.ERROR, error_msg)
            raise Exception(error_msg)

    def _get_aws_profiles(self) -> List[str]:
        """Get list of available AWS profiles from config files.
        
        Returns:
            List of profile names
        """
        profiles = set()
        
        # Check ~/.aws/config
        config_path = Path.home() / '.aws' / 'config'
        if config_path.exists():
            config = ConfigParser()
            config.read(config_path)
            for section in config.sections():
                # Profile sections are named 'profile <name>' in config file
                if section.startswith('profile '):
                    profiles.add(section.replace('profile ', ''))
                elif section == 'default':
                    profiles.add('default')
        
        # Check ~/.aws/credentials
        credentials_path = Path.home() / '.aws' / 'credentials'
        if credentials_path.exists():
            config = ConfigParser()
            config.read(credentials_path)
            for section in config.sections():
                profiles.add(section)
        
        return list(profiles)

    def _get_k8s_contexts(self) -> List[str]:
        """Get list of available Kubernetes contexts from kubeconfig.
        
        Returns:
            List of context names
        """
        kubeconfig_path = os.environ.get('KUBECONFIG', str(Path.home() / '.kube' / 'config'))
        
        if not Path(kubeconfig_path).exists():
            return []
        
        try:
            with open(kubeconfig_path, 'r') as f:
                kubeconfig = yaml.safe_load(f)
            
            if not kubeconfig or 'contexts' not in kubeconfig:
                return []
            
            contexts = []
            for context in kubeconfig.get('contexts', []):
                if 'name' in context:
                    contexts.append(context['name'])
            
            return contexts
            
        except Exception as e:
            logger.error(f'Failed to read kubeconfig: {str(e)}')
            return []
