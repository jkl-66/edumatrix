"""FAISS persistence regression tests for Task 2.3."""
import os
import shutil
import tempfile
import unittest

os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

from models import Evidence, EvidenceModality
from vector_store_faiss import FaissVectorIndex
from ingestion import DocumentIngestionPipeline


class TestFAISSPersistence(unittest.TestCase):
    """Verify FAISS indexes survive save/load round-trips."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="faiss_test_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_evidence(self, n: int) -> tuple[Evidence, ...]:
        return tuple(
            Evidence(
                id=f"test-ev-{i}",
                title=f"Test evidence {i}",
                content=f"This is test content about pooling and convolution {i}",
                modality=EvidenceModality.TEXT,
                source="test-source",
                tags=("pooling", "convolution"),
                anchors=("MaxPool2d", "Conv2d"),
            )
            for i in range(n)
        )

    def test_faiss_save_load_round_trip(self):
        """Index data survives serialization to disk and back."""
        original = FaissVectorIndex(name="round-trip-test")
        evidence = self._make_evidence(5)
        original.upsert(evidence)
        self.assertEqual(original.count(), 5)

        save_path = os.path.join(self.tmpdir, "round_trip_test")
        original.save(save_path)

        self.assertTrue(os.path.exists(save_path + ".faiss"))
        self.assertTrue(os.path.exists(save_path + ".json"))

        loaded = FaissVectorIndex.load(save_path)
        self.assertEqual(loaded.count(), 5)
        hits = loaded.search("pooling convolution", top_k=3)
        self.assertTrue(hits)
        hit_ids = {h.id for h in hits}
        self.assertTrue(hit_ids.issubset({f"test-ev-{i}" for i in range(5)}))

    def test_faiss_incremental_upsert_and_save(self):
        """Additional upserts merge correctly before and after save/load."""
        index = FaissVectorIndex(name="incremental-test")
        evidence_batch_1 = self._make_evidence(3)
        index.upsert(evidence_batch_1)
        self.assertEqual(index.count(), 3)

        save_path = os.path.join(self.tmpdir, "incremental_test")
        index.save(save_path)

        loaded = FaissVectorIndex.load(save_path)
        evidence_batch_2 = tuple(
            Evidence(
                id=f"extra-ev-{i}",
                title=f"Extra evidence {i}",
                content=f"Additional content about overfitting {i}",
                modality=EvidenceModality.TEXT,
                source="test-extra",
                tags=("overfitting", "regularization"),
                anchors=("L2", "dropout"),
            )
            for i in range(2)
        )
        loaded.upsert(evidence_batch_2)
        self.assertEqual(loaded.count(), 5)

        loaded.save(save_path)
        reloaded = FaissVectorIndex.load(save_path)
        self.assertEqual(reloaded.count(), 5)

    def test_ingestion_pipeline_persists_faiss_index(self):
        """DocumentIngestionPipeline triggers FAISS save when using FaissVectorIndex."""
        index = FaissVectorIndex(name="pipeline-persist-test")
        pipeline = DocumentIngestionPipeline(
            index,
            chunk_size=80,
            overlap=10,
            faiss_index_dir=self.tmpdir,
        )
        report = pipeline.ingest_text(
            "Maximum pooling uses a window to take the local maximum value. "
            "Confusion matrices can help students understand precision and recall differences.",
            source="unit-test.md",
            title="Industrialization Intro",
        )
        self.assertGreaterEqual(report.chunks, 1)
        self.assertTrue(report.persisted, "FAISS index should have been persisted")
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "pipeline-persist-test_index.faiss")))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "pipeline-persist-test_index.json")))

    def test_ingestion_pipeline_no_persist_for_in_memory(self):
        """InMemoryVectorIndex does not trigger persistence (graceful skip)."""
        from vector_store import InMemoryVectorIndex
        index = InMemoryVectorIndex("mem-test")
        pipeline = DocumentIngestionPipeline(
            index,
            chunk_size=80,
            overlap=10,
            faiss_index_dir=self.tmpdir,
        )
        report = pipeline.ingest_text(
            "Some text about machine learning.",
            source="test.md",
            title="Test",
        )
        self.assertGreaterEqual(report.chunks, 1)
        self.assertFalse(report.persisted, "InMemoryVectorIndex should not persist")

    def test_patches_image_files_exist(self):
        """All 7 VisRAG patch images are present on disk."""
        patches_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "patches",
        )
        expected = [
            "pooling_2x2.png",
            "avg_pooling.png",
            "conv_stride.png",
            "backprop_math.png",
            "ml_pipeline.png",
            "overfit_curve.png",
            "confusion_matrix.png",
        ]
        for filename in expected:
            path = os.path.join(patches_dir, filename)
            self.assertTrue(
                os.path.isfile(path),
                f"Missing VisRAG patch image: {filename}",
            )


if __name__ == "__main__":
    unittest.main()
