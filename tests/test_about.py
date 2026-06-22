from importlib.metadata import version

import s3fs_access_grants


class TestPackageVersion:
    def test_that_package_version_is_set(self):
        assert version("s3fs-access-grants") is not None

    def test_that_imported_module_version_is_set(self):
        assert s3fs_access_grants.__version__ is not None

    def test_that_module_version_matches_package_version(self):
        package_version = version("s3fs-access-grants")
        module_version = s3fs_access_grants.__version__
        assert module_version == package_version, (
            f"Module version {module_version} does not match package version {package_version}"
        )
