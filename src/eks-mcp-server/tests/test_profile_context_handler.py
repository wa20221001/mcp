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
# ruff: noqa: D101, D102, D103
"""Tests for the Profile Context Handler."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from awslabs.eks_mcp_server.aws_helper import AwsHelper
from awslabs.eks_mcp_server.k8s_client_cache import K8sClientCache
from awslabs.eks_mcp_server.profile_context_handler import ProfileContextHandler
from mcp.server.fastmcp import Context


class TestProfileContextHandler:
    """Tests for the ProfileContextHandler class."""

    def setup_method(self):
        """Set up the test environment."""
        # Clear caches and state
        AwsHelper._client_cache = {}
        AwsHelper._active_profile = None
        
        # Reset K8sClientCache singleton
        K8sClientCache._instance = None

    @pytest.fixture
    def mock_mcp(self):
        """Create a mock MCP server."""
        mcp = MagicMock()
        mcp.tool = lambda name: lambda func: func
        return mcp

    @pytest.fixture
    def handler(self, mock_mcp):
        """Create a ProfileContextHandler instance."""
        return ProfileContextHandler(mock_mcp)

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        context = MagicMock(spec=Context)
        context.request_id = 'test-request-id'
        return context

    @pytest.fixture
    def temp_aws_config(self):
        """Create a temporary AWS config file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            aws_dir = Path(temp_dir) / '.aws'
            aws_dir.mkdir()
            
            # Create config file
            config_file = aws_dir / 'config'
            config_file.write_text("""[default]
region = us-east-1

[profile test-profile]
region = us-west-2

[profile sso-profile]
sso_start_url = https://my-sso-portal.awsapps.com/start
sso_region = us-east-1
sso_account_id = 123456789012
sso_role_name = AdminRole
region = us-west-2

[profile another-profile]
region = eu-west-1
""")
            
            # Create credentials file
            creds_file = aws_dir / 'credentials'
            creds_file.write_text("""[default]
aws_access_key_id = AKIAIOSFODNN7EXAMPLE
aws_secret_access_key = wJalrXHELLO/K7MDENG/bPxRfiCYEXAMPLEKEY

[test-profile]
aws_access_key_id = AKIAIOSFODNN7EXAMPLE2
aws_secret_access_key = wJalrXGOODBYE/K7MDENG/bPxRfiCYEXAMPLEKEY2

[creds-only-profile]
aws_access_key_id = AKIAIOSFODNN7EXAMPLE3
aws_secret_access_key = wJalrXHIHIHI/K7MDENG/bPxRfiCYEXAMPLEKEY3
""")
            
            yield aws_dir

    @pytest.fixture
    def temp_kubeconfig(self):
        """Create a temporary kubeconfig file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            kube_dir = Path(temp_dir) / '.kube'
            kube_dir.mkdir()
            
            config_file = kube_dir / 'config'
            config_file.write_text("""apiVersion: v1
kind: Config
current-context: context1
contexts:
- name: context1
  context:
    cluster: cluster1
    user: user1
- name: context2
  context:
    cluster: cluster2
    user: user2
- name: eks-cluster-context
  context:
    cluster: eks-cluster
    user: eks-user
clusters:
- name: cluster1
  cluster:
    server: https://kubernetes.example.com:6443
- name: cluster2
  cluster:
    server: https://kubernetes2.example.com:6443
- name: eks-cluster
  cluster:
    server: https://eks.us-west-2.amazonaws.com
users:
- name: user1
  user:
    token: token1
- name: user2
  user:
    token: token2
- name: eks-user
  user:
    exec:
      command: aws
      args:
      - eks
      - get-token
      - --cluster-name
      - eks-cluster
""")
            
            yield config_file

    @pytest.mark.asyncio
    async def test_list_aws_profiles(self, handler, mock_context, temp_aws_config):
        """Test listing AWS profiles from config files."""
        with patch.object(Path, 'home', return_value=temp_aws_config.parent):
            result = await handler.list_aws_profiles(mock_context)
            
            # Verify profiles were found
            assert 'profiles' in result
            assert 'default' in result['profiles']
            assert 'test-profile' in result['profiles']
            assert 'sso-profile' in result['profiles']
            assert 'another-profile' in result['profiles']
            assert 'creds-only-profile' in result['profiles']

    @pytest.mark.asyncio
    async def test_list_aws_profiles_no_config_files(self, handler, mock_context):
        """Test listing AWS profiles when config files don't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(Path, 'home', return_value=Path(temp_dir)):
                result = await handler.list_aws_profiles(mock_context)
                
                # Should return empty list
                assert 'profiles' in result
                assert len(result['profiles']) == 0

    @pytest.mark.asyncio
    async def test_set_aws_profile_valid(self, handler, mock_context, temp_aws_config):
        """Test setting a valid AWS profile."""
        with patch.object(Path, 'home', return_value=temp_aws_config.parent):
            result = await handler.set_aws_profile(mock_context, 'test-profile')
            
            # Verify profile was set
            assert 'test-profile' in result
            assert AwsHelper.get_active_profile() == 'test-profile'

    @pytest.mark.asyncio
    async def test_set_aws_profile_sso(self, handler, mock_context, temp_aws_config):
        """Test setting an AWS SSO profile."""
        with patch.object(Path, 'home', return_value=temp_aws_config.parent):
            result = await handler.set_aws_profile(mock_context, 'sso-profile')
            
            # Verify SSO profile was set
            assert 'sso-profile' in result
            assert AwsHelper.get_active_profile() == 'sso-profile'

    @pytest.mark.asyncio
    async def test_set_aws_profile_invalid(self, handler, mock_context, temp_aws_config):
        """Test setting an invalid AWS profile."""
        with patch.object(Path, 'home', return_value=temp_aws_config.parent):
            with pytest.raises(Exception) as exc_info:
                await handler.set_aws_profile(mock_context, 'nonexistent-profile')
            
            assert 'not found' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_aws_profile_when_set(self, handler, mock_context):
        """Test getting AWS profile when it's set."""
        AwsHelper.set_active_profile('test-profile')
        
        result = await handler.get_aws_profile(mock_context)
        
        assert 'test-profile' in result

    @pytest.mark.asyncio
    async def test_get_aws_profile_when_not_set(self, handler, mock_context):
        """Test getting AWS profile when it's not set."""
        AwsHelper._active_profile = None
        
        with patch.dict(os.environ, {}, clear=True):
            result = await handler.get_aws_profile(mock_context)
            
            assert 'No AWS profile' in result

    @pytest.mark.asyncio
    async def test_list_k8s_contexts(self, handler, mock_context, temp_kubeconfig):
        """Test listing Kubernetes contexts from kubeconfig."""
        with patch.dict(os.environ, {'KUBECONFIG': str(temp_kubeconfig)}):
            result = await handler.list_k8s_contexts(mock_context)
            
            # Verify contexts were found
            assert 'contexts' in result
            assert 'context1' in result['contexts']
            assert 'context2' in result['contexts']
            assert 'eks-cluster-context' in result['contexts']

    @pytest.mark.asyncio
    async def test_list_k8s_contexts_no_config(self, handler, mock_context):
        """Test listing Kubernetes contexts when kubeconfig doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_path = Path(temp_dir) / 'nonexistent' / 'config'
            with patch.dict(os.environ, {'KUBECONFIG': str(fake_path)}):
                result = await handler.list_k8s_contexts(mock_context)
                
                # Should return empty list
                assert 'contexts' in result
                assert len(result['contexts']) == 0

    @pytest.mark.asyncio
    async def test_set_k8s_context_valid(self, handler, mock_context, temp_kubeconfig):
        """Test setting a valid Kubernetes context."""
        with patch.dict(os.environ, {'KUBECONFIG': str(temp_kubeconfig)}):
            result = await handler.set_k8s_context(mock_context, 'context2')
            
            # Verify context was set
            assert 'context2' in result
            
            # Verify in K8sClientCache
            cache = K8sClientCache()
            assert cache.get_active_context() == 'context2'

    @pytest.mark.asyncio
    async def test_set_k8s_context_eks(self, handler, mock_context, temp_kubeconfig):
        """Test setting an EKS Kubernetes context."""
        with patch.dict(os.environ, {'KUBECONFIG': str(temp_kubeconfig)}):
            result = await handler.set_k8s_context(mock_context, 'eks-cluster-context')
            
            # Verify EKS context was set
            assert 'eks-cluster-context' in result
            
            # Verify in K8sClientCache
            cache = K8sClientCache()
            assert cache.get_active_context() == 'eks-cluster-context'

    @pytest.mark.asyncio
    async def test_set_k8s_context_invalid(self, handler, mock_context, temp_kubeconfig):
        """Test setting an invalid Kubernetes context."""
        with patch.dict(os.environ, {'KUBECONFIG': str(temp_kubeconfig)}):
            with pytest.raises(Exception) as exc_info:
                await handler.set_k8s_context(mock_context, 'nonexistent-context')
            
            assert 'not found' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_k8s_context_when_set(self, handler, mock_context):
        """Test getting Kubernetes context when it's set."""
        cache = K8sClientCache()
        cache.set_active_context('test-context')
        
        result = await handler.get_k8s_context(mock_context)
        
        assert 'test-context' in result

    @pytest.mark.asyncio
    async def test_get_k8s_context_when_not_set(self, handler, mock_context):
        """Test getting Kubernetes context when it's not set."""
        result = await handler.get_k8s_context(mock_context)
        
        assert 'No Kubernetes context' in result

    @pytest.mark.asyncio
    async def test_profile_switching_workflow(self, handler, mock_context, temp_aws_config):
        """Test a complete workflow of switching between profiles."""
        with patch.object(Path, 'home', return_value=temp_aws_config.parent):
            # List profiles
            profiles = await handler.list_aws_profiles(mock_context)
            assert 'test-profile' in profiles['profiles']
            
            # Set first profile
            await handler.set_aws_profile(mock_context, 'test-profile')
            result = await handler.get_aws_profile(mock_context)
            assert 'test-profile' in result
            
            # Switch to another profile
            await handler.set_aws_profile(mock_context, 'another-profile')
            result = await handler.get_aws_profile(mock_context)
            assert 'another-profile' in result
            
            # Verify cache was cleared on switch
            assert len(AwsHelper._client_cache) == 0

    @pytest.mark.asyncio
    async def test_context_switching_workflow(self, handler, mock_context, temp_kubeconfig):
        """Test a complete workflow of switching between contexts."""
        with patch.dict(os.environ, {'KUBECONFIG': str(temp_kubeconfig)}):
            # List contexts
            contexts = await handler.list_k8s_contexts(mock_context)
            assert 'context1' in contexts['contexts']
            
            # Set first context
            await handler.set_k8s_context(mock_context, 'context1')
            result = await handler.get_k8s_context(mock_context)
            assert 'context1' in result
            
            # Switch to another context
            await handler.set_k8s_context(mock_context, 'context2')
            result = await handler.get_k8s_context(mock_context)
            assert 'context2' in result

    @pytest.mark.asyncio
    async def test_multiple_profile_types(self, handler, mock_context, temp_aws_config):
        """Test handling different types of AWS profiles (regular, SSO, credentials-only)."""
        with patch.object(Path, 'home', return_value=temp_aws_config.parent):
            # Test regular profile
            await handler.set_aws_profile(mock_context, 'test-profile')
            assert AwsHelper.get_active_profile() == 'test-profile'
            
            # Test SSO profile
            await handler.set_aws_profile(mock_context, 'sso-profile')
            assert AwsHelper.get_active_profile() == 'sso-profile'
            
            # Test credentials-only profile
            await handler.set_aws_profile(mock_context, 'creds-only-profile')
            assert AwsHelper.get_active_profile() == 'creds-only-profile'
            
            # Test default profile
            await handler.set_aws_profile(mock_context, 'default')
            assert AwsHelper.get_active_profile() == 'default'
