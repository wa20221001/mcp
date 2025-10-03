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
"""Tests for the AWS Helper."""

import os
import threading
from awslabs.eks_mcp_server import __version__
from awslabs.eks_mcp_server.aws_helper import AwsHelper
from unittest.mock import ANY, MagicMock, patch


class TestAwsHelper:
    """Tests for the AwsHelper class."""

    def setup_method(self):
        """Set up the test environment."""
        # Clear the client cache before each test
        AwsHelper._client_cache = {}
        AwsHelper._active_profile = None

    @patch.dict(os.environ, {'AWS_REGION': 'us-west-2'})
    def test_get_aws_region_from_env(self):
        """Test that get_aws_region returns the region from the environment."""
        region = AwsHelper.get_aws_region()
        assert region == 'us-west-2'

    @patch.dict(os.environ, {}, clear=True)
    def test_get_aws_region_default(self):
        """Test that get_aws_region returns None when not set in the environment."""
        region = AwsHelper.get_aws_region()
        assert region is None

    @patch.dict(os.environ, {'AWS_PROFILE': 'test-profile'})
    def test_get_aws_profile_from_env(self):
        """Test that get_aws_profile returns the profile from the environment."""
        profile = AwsHelper.get_aws_profile()
        assert profile == 'test-profile'

    @patch.dict(os.environ, {}, clear=True)
    def test_get_aws_profile_none(self):
        """Test that get_aws_profile returns None when not set in the environment."""
        profile = AwsHelper.get_aws_profile()
        assert profile is None

    @patch('boto3.Session')
    def test_create_boto3_client_no_profile_with_region(self, mock_session_cls):
        """Test client creation with environment region and no explicit profile."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        with patch.dict(os.environ, {'AWS_REGION': 'us-west-2'}):
            with patch.object(AwsHelper, 'get_aws_profile', return_value=None):
                with patch.object(AwsHelper, 'get_aws_region', return_value='us-west-2'):
                    AwsHelper.create_boto3_client('cloudformation')

        mock_session_cls.assert_called_once_with(region_name='us-west-2')
        mock_session.client.assert_called_once_with(
            'cloudformation', region_name='us-west-2', config=ANY
        )

    @patch('boto3.Session')
    def test_create_boto3_client_no_profile_no_region(self, mock_session_cls):
        """Test client creation without region or profile uses default session."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(AwsHelper, 'get_aws_profile', return_value=None):
                with patch.object(AwsHelper, 'get_aws_region', return_value=None):
                    AwsHelper.create_boto3_client('cloudformation')

        mock_session_cls.assert_called_once_with()
        mock_session.client.assert_called_once_with('cloudformation', config=ANY)

    @patch('boto3.Session')
    def test_create_boto3_client_with_profile_with_region(self, mock_boto3_session):
        """Test that create_boto3_client creates a client with the correct parameters when a profile is set and region is in env."""
        # Create a mock session
        mock_session = MagicMock()
        mock_boto3_session.return_value = mock_session

        # Mock the get_aws_profile method to return a profile
        with patch.object(AwsHelper, 'get_aws_profile', return_value='test-profile'):
            # Mock the get_aws_region method to return a specific region
            with patch.dict(os.environ, {'AWS_REGION': 'us-west-2'}):
                with patch.object(AwsHelper, 'get_aws_region', return_value='us-west-2'):
                    # Call the create_boto3_client method
                    AwsHelper.create_boto3_client('cloudformation')

                    # Verify that boto3.Session was called with the correct parameters
                    mock_boto3_session.assert_called_once_with(
                        profile_name='test-profile', region_name='us-west-2'
                    )

                    # Verify that session.client was called with the correct parameters
                    mock_session.client.assert_called_once_with(
                        'cloudformation', region_name='us-west-2', config=ANY
                    )

    @patch('boto3.Session')
    def test_create_boto3_client_with_profile_no_region(self, mock_boto3_session):
        """Test that create_boto3_client creates a client without region when a profile is set but no region."""
        # Create a mock session
        mock_session = MagicMock()
        mock_boto3_session.return_value = mock_session

        # Mock the get_aws_profile method to return a profile
        with patch.object(AwsHelper, 'get_aws_profile', return_value='test-profile'):
            # Mock the get_aws_region method to return None
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(AwsHelper, 'get_aws_region', return_value=None):
                    # Call the create_boto3_client method
                    AwsHelper.create_boto3_client('cloudformation')

                    # Verify that boto3.Session was called with the correct parameters
                    mock_boto3_session.assert_called_once_with(profile_name='test-profile')

                    # Verify that session.client was called without region_name
                    mock_session.client.assert_called_once_with('cloudformation', config=ANY)

    @patch('boto3.Session')
    def test_create_boto3_client_with_region_override(self, mock_session_cls):
        """Test that explicit region argument overrides environment/default."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        with patch.object(AwsHelper, 'get_aws_profile', return_value=None):
            AwsHelper.create_boto3_client('cloudformation', region_name='eu-west-1')

        mock_session_cls.assert_called_once_with(region_name='eu-west-1')
        mock_session.client.assert_called_once_with(
            'cloudformation', region_name='eu-west-1', config=ANY
        )

    def test_create_boto3_client_user_agent(self):
        """Test that create_boto3_client sets the user agent suffix correctly using the package version."""
        # Create a real Config object to inspect
        with patch.object(AwsHelper, 'get_aws_profile', return_value=None):
            with patch.object(AwsHelper, 'get_aws_region', return_value=None):
                with patch('boto3.Session') as mock_session_cls:
                    mock_session = MagicMock()
                    mock_client = MagicMock()
                    mock_session.client.return_value = mock_client
                    mock_session_cls.return_value = mock_session

                    AwsHelper.create_boto3_client('cloudformation')

                    _, kwargs = mock_session.client.call_args
                    config = kwargs.get('config')

                    assert config is not None
                    expected_user_agent = f'awslabs/mcp/eks-mcp-server/{__version__}'
                    assert config.user_agent_extra == expected_user_agent

    @patch('boto3.Session')
    def test_client_caching(self, mock_session_cls):
        """Test that identical service/region/profile combinations reuse cached clients."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_session_cls.return_value = mock_session

        with patch.object(AwsHelper, 'get_aws_profile', return_value=None):
            with patch.object(AwsHelper, 'get_aws_region', return_value='us-west-2'):
                client1 = AwsHelper.create_boto3_client('cloudformation')
                client2 = AwsHelper.create_boto3_client('cloudformation')

        mock_session_cls.assert_called_once_with(region_name='us-west-2')
        mock_session.client.assert_called_once()
        assert client1 is client2

    @patch('boto3.Session')
    def test_different_services_not_cached_together(self, mock_session_cls):
        """Test that each service gets its own cached client entry."""
        mock_session = MagicMock()
        mock_cf_client = MagicMock()
        mock_s3_client = MagicMock()
        mock_session.client.side_effect = [mock_cf_client, mock_s3_client]
        mock_session_cls.return_value = mock_session

        with patch.object(AwsHelper, 'get_aws_profile', return_value=None):
            with patch.object(AwsHelper, 'get_aws_region', return_value='us-west-2'):
                cf_client = AwsHelper.create_boto3_client('cloudformation')
                s3_client = AwsHelper.create_boto3_client('s3')

        assert mock_session.client.call_count == 2
        assert cf_client is not s3_client

    @patch('boto3.Session')
    def test_same_service_different_regions_not_cached_together(self, mock_session_cls):
        """Test that changing region results in a new cached client."""
        mock_session = MagicMock()
        mock_us_client = MagicMock()
        mock_eu_client = MagicMock()
        mock_session.client.side_effect = [mock_us_client, mock_eu_client]
        mock_session_cls.return_value = mock_session

        with patch.object(AwsHelper, 'get_aws_profile', return_value=None):
            us_west_client = AwsHelper.create_boto3_client(
                'cloudformation', region_name='us-west-2'
            )
            eu_west_client = AwsHelper.create_boto3_client(
                'cloudformation', region_name='eu-west-1'
            )

        assert mock_session.client.call_count == 2
        assert us_west_client is not eu_west_client

    @patch('boto3.Session')
    def test_error_handling(self, mock_session_cls):
        """Test that errors during client creation are handled properly."""
        # Make boto3.client raise an exception
        mock_session = MagicMock()
        mock_session.client.side_effect = Exception('Test error')
        mock_session_cls.return_value = mock_session

        # Mock the get_aws_profile and get_aws_region methods
        with patch.object(AwsHelper, 'get_aws_profile', return_value=None):
            with patch.object(AwsHelper, 'get_aws_region', return_value=None):
                # Verify that the exception is re-raised with more context
                try:
                    AwsHelper.create_boto3_client('cloudformation')
                    assert False, 'Exception was not raised'
                except Exception as e:
                    assert 'Failed to create boto3 client for cloudformation: Test error' in str(e)

    @patch('boto3.Session')
    def test_same_service_different_profiles_not_cached_together(self, mock_boto3_session):
        """Test that changing profile invalidates cached client."""
        mock_session1 = MagicMock()
        mock_client1 = MagicMock()
        mock_session1.client.return_value = mock_client1

        mock_session2 = MagicMock()
        mock_client2 = MagicMock()
        mock_session2.client.return_value = mock_client2

        mock_boto3_session.side_effect = [mock_session1, mock_session2]

        with patch.object(AwsHelper, 'get_aws_region', return_value=None):
            with patch.object(AwsHelper, 'get_aws_profile', return_value='profile1'):
                client1 = AwsHelper.create_boto3_client('cloudformation')

            with patch.object(AwsHelper, 'get_aws_profile', return_value='profile2'):
                client2 = AwsHelper.create_boto3_client('cloudformation')

        assert mock_boto3_session.call_count == 2
        assert client1 is not client2

    def test_set_active_profile(self):
        """Test that set_active_profile sets the profile and clears cache."""
        # Add some items to the cache
        AwsHelper._client_cache[('s3', None, None)] = MagicMock()
        AwsHelper._client_cache[('ec2', None, None)] = MagicMock()
        
        # Set active profile
        AwsHelper.set_active_profile('test-profile')
        
        # Verify profile was set
        assert AwsHelper._active_profile == 'test-profile'
        
        # Verify cache was cleared
        assert len(AwsHelper._client_cache) == 0

    def test_set_active_profile_to_none(self):
        """Test that set_active_profile can be set to None."""
        # Set active profile to a value first
        AwsHelper._active_profile = 'test-profile'
        
        # Set to None
        AwsHelper.set_active_profile(None)
        
        # Verify profile was set to None
        assert AwsHelper._active_profile is None

    def test_get_active_profile_when_set(self):
        """Test that get_active_profile returns the active profile when set."""
        # Set active profile
        AwsHelper._active_profile = 'test-profile'
        
        # Get active profile
        profile = AwsHelper.get_active_profile()
        
        # Verify correct profile was returned
        assert profile == 'test-profile'

    @patch.dict(os.environ, {'AWS_PROFILE': 'env-profile'})
    def test_get_active_profile_falls_back_to_env(self):
        """Test that get_active_profile falls back to environment variable when not set."""
        # Ensure active profile is None
        AwsHelper._active_profile = None
        
        # Get active profile
        profile = AwsHelper.get_active_profile()
        
        # Verify env profile was returned
        assert profile == 'env-profile'

    @patch.dict(os.environ, {}, clear=True)
    def test_get_active_profile_returns_none_when_not_set(self):
        """Test that get_active_profile returns None when neither active profile nor env is set."""
        # Ensure active profile is None
        AwsHelper._active_profile = None
        
        # Get active profile
        profile = AwsHelper.get_active_profile()
        
        # Verify None was returned
        assert profile is None

    @patch('boto3.Session')
    def test_active_profile_overrides_env_profile(self, mock_boto3_session):
        """Test that active profile overrides environment variable."""
        # Create mock session
        mock_session = MagicMock()
        mock_boto3_session.return_value = mock_session
        
        # Set environment profile
        with patch.dict(os.environ, {'AWS_PROFILE': 'env-profile'}):
            # Set active profile to override
            AwsHelper.set_active_profile('active-profile')
            
            # Create client
            AwsHelper.create_boto3_client('s3')
            
            # Verify Session was created with active profile, not env profile
            mock_boto3_session.assert_called_once_with(profile_name='active-profile')

    @patch('boto3.Session')
    def test_profile_switching_clears_cache(self, mock_boto3_session):
        """Test that switching profiles causes clients to be recreated."""
        # Create mock sessions and clients
        mock_session1 = MagicMock()
        mock_client1 = MagicMock()
        mock_session1.client.return_value = mock_client1
        
        mock_session2 = MagicMock()
        mock_client2 = MagicMock()
        mock_session2.client.return_value = mock_client2
        
        mock_boto3_session.side_effect = [mock_session1, mock_session2]
        
        # Create client with first profile
        AwsHelper.set_active_profile('profile1')
        with patch.object(AwsHelper, 'get_aws_region', return_value=None):
            client1 = AwsHelper.create_boto3_client('s3')
        
        # Switch profile
        AwsHelper.set_active_profile('profile2')
        
        # Create client again
        with patch.object(AwsHelper, 'get_aws_region', return_value=None):
            client2 = AwsHelper.create_boto3_client('s3')
        
        # Verify both sessions were created
        assert mock_boto3_session.call_count == 2
        
        # Verify different clients were returned
        assert client1 is not client2

    @patch('boto3.Session')
    def test_aws_sso_profile_support(self, mock_boto3_session):
        """Test that AWS SSO profiles work correctly."""
        # Create mock session
        mock_session = MagicMock()
        mock_boto3_session.return_value = mock_session
        
        # Set an SSO profile
        AwsHelper.set_active_profile('my-sso-profile')
        
        # Create client
        with patch.object(AwsHelper, 'get_aws_region', return_value='us-east-1'):
            AwsHelper.create_boto3_client('s3')
        
        # Verify Session was created with SSO profile
        mock_boto3_session.assert_called_once_with(
            profile_name='my-sso-profile', region_name='us-east-1'
        )
        
        # Verify client was created with region
        mock_session.client.assert_called_once_with('s3', region_name='us-east-1', config=ANY)

    @patch('boto3.Session')
    def test_create_boto3_client_thread_safe(self, mock_boto3_session):
        """Test that concurrent client creation uses cached instance."""
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_boto3_session.return_value = mock_session

        def worker(results):
            client = AwsHelper.create_boto3_client('s3', region_name='us-east-1')
            results.append(client)

        threads = []
        results = []
        for _ in range(5):
            thread = threading.Thread(target=worker, args=(results,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Ensure only one underlying client creation occurred
        mock_session.client.assert_called_once()
        assert len({id(client) for client in results}) == 1
