from app.skill_security import package_digest, sign_digest, verify_signature


def test_skill_signature_detects_manifest_tampering(tmp_path) -> None:
    directory = tmp_path / "skill"
    directory.mkdir()
    manifest = {"id": "signed", "version": "1.0.0", "permissions": {"network": ["example.test"]}}
    digest = package_digest(directory, manifest)
    signature = sign_digest(digest)
    assert verify_signature(digest, signature) is True
    tampered = package_digest(directory, {**manifest, "version": "1.0.1"})
    assert verify_signature(tampered, signature) is False
