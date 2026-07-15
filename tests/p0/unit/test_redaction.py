from __future__ import annotations

import json
import unittest

from p0_baseline.redaction import (
    DROPPED_PLACEHOLDER,
    REDACTED_PLACEHOLDER,
    TRUNCATED_PLACEHOLDER,
    RedactionResult,
    redact,
)


SECRET = "p0-test-secret-7f3a9b"
SECOND_SECRET = "p0-test-secret-c2d841"


def serialized(result: RedactionResult) -> str:
    return json.dumps(result.value, sort_keys=True, separators=(",", ":"))


class RedactionTests(unittest.TestCase):
    def assertSecretsAbsent(self, result: RedactionResult) -> None:  # noqa: N802
        output = serialized(result)
        self.assertNotIn(SECRET, output)
        self.assertNotIn(SECOND_SECRET, output)

    def test_nested_values_and_case_insensitive_sensitive_keys_are_redacted(self) -> None:
        source = {
            "safe": [1, True, None, 2.5, {"ApiKey": SECRET}],
            "nested": {"PASSWORD_hint": SECOND_SECRET, "ordinary": "visible"},
        }

        result = redact(source)

        self.assertEqual(REDACTED_PLACEHOLDER, result.value["safe"][4]["ApiKey"])
        self.assertEqual(REDACTED_PLACEHOLDER, result.value["nested"]["PASSWORD_hint"])
        self.assertEqual("visible", result.value["nested"]["ordinary"])
        self.assertEqual(2, result.matched_values)
        self.assertSecretsAbsent(result)

    def test_headers_are_redacted_by_header_name(self) -> None:
        source = {
            "headers": {
                "Authorization": SECRET,
                "X-Api-Key": SECOND_SECRET,
                "Accept": "application/json",
            }
        }

        result = redact(source)

        self.assertEqual(REDACTED_PLACEHOLDER, result.value["headers"]["Authorization"])
        self.assertEqual(REDACTED_PLACEHOLDER, result.value["headers"]["X-Api-Key"])
        self.assertEqual("application/json", result.value["headers"]["Accept"])
        self.assertEqual(2, result.matched_values)
        self.assertSecretsAbsent(result)

    def test_url_removes_userinfo_query_values_and_fragment(self) -> None:
        url = (
            f"https://alice:{SECRET}@example.test:8443/path/to/item"
            f"?page={SECOND_SECRET}&token={SECRET}"
            f"&secret-label-{SECRET}=visible#fragment-{SECRET}"
        )

        result = redact({"target_url": url})
        safe_url = result.value["target_url"]

        self.assertTrue(safe_url.startswith("https://example.test:8443/path/to/item?"))
        self.assertIn("page=%3Credacted%3E", safe_url)
        self.assertNotIn("token=", safe_url)
        self.assertIn("%3Credacted%3E=%3Credacted%3E", safe_url)
        self.assertNotIn("@", safe_url)
        self.assertNotIn("#", safe_url)
        self.assertGreaterEqual(result.matched_values, 4)
        self.assertSecretsAbsent(result)

    def test_forbidden_raw_categories_and_exception_details_are_replaced(self) -> None:
        source = {
            "traceback": f"Traceback: {SECRET}",
            "exception_detail": SECOND_SECRET,
            "prompt": SECOND_SECRET,
            "model_raw_response": SECRET,
            "tool_full_result": SECOND_SECRET,
            "error": RuntimeError(SECRET),
        }

        result = redact(source)

        self.assertEqual(REDACTED_PLACEHOLDER, result.value["traceback"])
        self.assertEqual(REDACTED_PLACEHOLDER, result.value["exception_detail"])
        self.assertEqual(REDACTED_PLACEHOLDER, result.value["prompt"])
        self.assertEqual(REDACTED_PLACEHOLDER, result.value["model_raw_response"])
        self.assertEqual(REDACTED_PLACEHOLDER, result.value["tool_full_result"])
        self.assertEqual(DROPPED_PLACEHOLDER, result.value["error"])
        self.assertEqual(5, result.matched_values)
        self.assertEqual(1, result.dropped)
        self.assertSecretsAbsent(result)

    def test_request_body_canonical_keys_replace_the_entire_value(self) -> None:
        for key in ("request_body", "Request-Body", "request body", "body"):
            with self.subTest(key=key):
                result = redact({key: {"message": SECRET}, "somebody": "visible"})
                self.assertEqual(REDACTED_PLACEHOLDER, result.value[key])
                self.assertEqual("visible", result.value["somebody"])
                self.assertEqual(1, result.matched_values)
                self.assertSecretsAbsent(result)

    def test_tool_result_canonical_key_replaces_the_entire_value(self) -> None:
        for key in ("tool_result", "Tool-Result", "tool result"):
            with self.subTest(key=key):
                result = redact({key: {"content": SECRET}, "result_count": 1})
                self.assertEqual(REDACTED_PLACEHOLDER, result.value[key])
                self.assertEqual(1, result.value["result_count"])
                self.assertEqual(1, result.matched_values)
                self.assertSecretsAbsent(result)

    def test_request_payload_semantic_keys_replace_the_entire_value(self) -> None:
        keys = (
            "request_payload",
            "request-content",
            "request data",
            "requestBody",
            "HTTPRequestPayload",
        )
        for key in keys:
            with self.subTest(key=key):
                result = redact({key: {"message": SECRET}})
                self.assertEqual(REDACTED_PLACEHOLDER, result.value[key])
                self.assertEqual(1, result.matched_values)
                self.assertSecretsAbsent(result)

    def test_tool_result_semantic_keys_replace_the_entire_value(self) -> None:
        keys = (
            "tool_output",
            "tool-response",
            "tool result",
            "toolResult",
            "FullToolResponse",
        )
        for key in keys:
            with self.subTest(key=key):
                result = redact({key: {"content": SECRET}})
                self.assertEqual(REDACTED_PLACEHOLDER, result.value[key])
                self.assertEqual(1, result.matched_values)
                self.assertSecretsAbsent(result)

    def test_request_and_tool_containers_fail_closed_for_unknown_suffixes(self) -> None:
        keys = (
            "request_json",
            "requestJSON",
            "HTTPRequestJSON",
            "request_future_envelope_v99",
            "tool_json",
            "toolFutureEnvelopeV99",
        )
        for key in keys:
            with self.subTest(key=key):
                result = redact({key: {"value": SECRET}})
                self.assertEqual(REDACTED_PLACEHOLDER, result.value[key])
                self.assertEqual(1, result.matched_values)
                self.assertSecretsAbsent(result)

    def test_tool_metadata_strings_are_not_treated_as_provably_safe(self) -> None:
        for key, short_secret in (
            ("tool_name", "private-tool-z9"),
            ("tool_status", "private-status-q8"),
        ):
            with self.subTest(key=key):
                result = redact({key: short_secret})
                self.assertEqual(REDACTED_PLACEHOLDER, result.value[key])
                self.assertNotIn(short_secret, serialized(result))
                self.assertEqual(1, result.matched_values)

    def test_safe_count_metadata_requires_an_approved_integer_range(self) -> None:
        safe_metadata = {
            "request_count": 2,
            "result_count": 1,
        }
        self.assertEqual(safe_metadata, redact(safe_metadata).value)

        for key in safe_metadata:
            for unsafe_value in (
                {"value": SECRET},
                -1,
                True,
                "1",
                1 << 63,
            ):
                with self.subTest(key=key, unsafe_value=unsafe_value):
                    result = redact({key: unsafe_value})
                    self.assertEqual(REDACTED_PLACEHOLDER, result.value[key])
                    self.assertEqual(1, result.matched_values)
                    self.assertSecretsAbsent(result)

    def test_semantic_key_classification_preserves_near_misses(self) -> None:
        source = {
            "somebody": "visible-1",
            "embody": "visible-2",
            "requester": {"name": "visible-3"},
            "toolbox": {"name": "visible-4"},
            "result_count": 1,
            "request_count": 2,
        }

        result = redact(source)

        self.assertEqual(source, result.value)
        self.assertEqual(0, result.matched_values)

    def test_cycles_and_unsupported_or_hostile_objects_fail_closed(self) -> None:
        class Hostile:
            def __str__(self) -> str:
                raise AssertionError("must not stringify hostile input")

            def __repr__(self) -> str:
                raise AssertionError("must not repr hostile input")

            @property
            def detail(self) -> str:
                raise AssertionError("must not inspect attributes")

        cyclic: list[object] = []
        cyclic.append(cyclic)
        source = {"cycle": cyclic, "hostile": Hostile(), "opaque": object()}

        result = redact(source)

        self.assertEqual(DROPPED_PLACEHOLDER, result.value["cycle"][0])
        self.assertEqual(DROPPED_PLACEHOLDER, result.value["hostile"])
        self.assertEqual(DROPPED_PLACEHOLDER, result.value["opaque"])
        self.assertEqual(3, result.dropped)
        json.dumps(result.value)

    def test_depth_string_collection_node_and_output_limits_are_deterministic(self) -> None:
        source = {
            "deep": {"level1": {"level2": {"value": "visible"}}},
            "long": "abcdefghij",
            "many": [1, 2, 3, 4],
        }
        limited = redact(
            source,
            max_depth=2,
            max_items=3,
            max_string_length=5,
            max_nodes=20,
            max_output_chars=200,
        )

        self.assertEqual(TRUNCATED_PLACEHOLDER, limited.value["deep"]["level1"])
        self.assertEqual("abcde" + TRUNCATED_PLACEHOLDER, limited.value["long"])
        self.assertEqual([1, 2, 3, TRUNCATED_PLACEHOLDER], limited.value["many"])
        self.assertGreaterEqual(limited.truncated, 3)
        self.assertEqual(serialized(limited), serialized(redact(
            source,
            max_depth=2,
            max_items=3,
            max_string_length=5,
            max_nodes=20,
            max_output_chars=200,
        )))

        node_limited = redact([{"a": 1}, {"b": 2}], max_nodes=2)
        self.assertIn(TRUNCATED_PLACEHOLDER, serialized(node_limited))
        output_limited = redact({"safe": "abcdefghij"}, max_output_chars=20)
        self.assertEqual(TRUNCATED_PLACEHOLDER, output_limited.value)
        self.assertLessEqual(len(serialized(output_limited)), 20)
        with self.assertRaises(ValueError):
            redact({"safe": "visible"}, max_output_chars=12)

    def test_source_is_unchanged_result_is_frozen_and_json_serializable(self) -> None:
        source = {"Password": SECRET, "items": ["safe"]}
        original = {"Password": SECRET, "items": ["safe"]}

        result = redact(source)

        self.assertEqual(original, source)
        self.assertEqual(result, RedactionResult(
            value=result.value,
            matched_values=result.matched_values,
            truncated=result.truncated,
            dropped=result.dropped,
        ))
        with self.assertRaises((AttributeError, TypeError)):
            result.matched_values = 0  # type: ignore[misc]
        with self.assertRaises(TypeError):
            result.value["new"] = "unsafe"  # type: ignore[index]
        json.loads(serialized(result))
        self.assertSecretsAbsent(result)


if __name__ == "__main__":
    unittest.main()
