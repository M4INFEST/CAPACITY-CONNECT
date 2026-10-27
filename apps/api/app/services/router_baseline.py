"""
Builds and saves the deterministic TF-IDF baseline router.joblib for Capacity Connect Stage 2 (C14).
Provides held-out test data for comparative precision evaluation between baseline and LLM extractors.
"""

import os
from dataclasses import dataclass
from typing import Any
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline


ROUTER_PATH = os.path.join(os.path.dirname(__file__), "router.joblib")


TRAIN_DATA = [
    # C
    ("Implemented embedded firmware in C programming language with hardware memory constraints.", "C"),
    ("Wrote kernel drivers using low-level C compiler and pointer arithmetic.", "C"),
    ("Embedded systems engineer with 5 years of C code optimization and memory management.", "C"),
    # C++
    ("High-frequency trading engine authored in modern C++ with templates and STL algorithms.", "C++"),
    ("Game development in Unreal Engine using C++ and multi-threaded rendering.", "C++"),
    ("Developed real-time computer vision algorithms in C++20.", "C++"),
    # C#
    ("Built enterprise desktop software in C# utilizing WPF and LINQ queries.", "C#"),
    ("Developed backend microservices in C# with Entity Framework Core and ASP.NET.", "C#"),
    ("Game programmer writing C# scripts and game logic inside Unity.", "C#"),
    # .NET
    ("Enterprise architecture built on Microsoft .NET Core and Azure App Services.", ".NET"),
    ("Maintained legacy ASP.NET WebForms and migrated to .NET 8.", ".NET"),
    ("Full-stack engineer working on .NET microservices and SQL Server databases.", ".NET"),
    # Node.js
    ("Architected asynchronous microservices using Node.js, Express, and event loops.", "Node.js"),
    ("Full-stack JavaScript engineer building high-throughput APIs in Node.js.", "Node.js"),
    ("Server-side scripting and WebSocket services running on Node.js runtime.", "Node.js"),
    # Java
    ("Enterprise backend applications developed in Java with Spring Boot framework.", "Java"),
    ("Android application development utilizing Java and JVM memory tuning.", "Java"),
    ("Distributed batch processing pipelines authored in Java 17.", "Java"),
    # JavaScript
    ("Dynamic browser user interfaces constructed with JavaScript and modern DOM APIs.", "JavaScript"),
    ("Client-side frontend development using vanilla JavaScript and ES6 modules.", "JavaScript"),
    ("Interactive web components created with JavaScript and CSS3 animations.", "JavaScript"),
]


# Hand-written held-out evaluation set for comparative precision benchmark
HELDOUT_TEST_SET = [
    # High-confidence true positives with exact boundary tests
    ("Engineered real-time graphics pipeline using C++ and Vulkan shaders.", "C++", "C++"),
    ("Wrote low-level microcontroller drivers using C language compiler.", "C", "C"),
    ("Built scalable distributed backends in Java and Spring Data JPA.", "Java", "Java"),
    ("Created responsive client-side UI with pure JavaScript and HTML5 canvas.", "JavaScript", "JavaScript"),
    ("Developed scalable REST API gateway in Node.js with clustering.", "Node.js", "Node.js"),
    ("Built cloud-native microservices using .NET Core runtime and C# language.", "C#", "C#"),
    ("Enterprise distributed systems deployed on Microsoft .NET platform.", ".NET", ".NET"),
    # Tricky symbol / substring test cases:
    # JavaScript should never match Java
    ("We only use JavaScript for web pages; no JVM or Java backends.", "JavaScript", "JavaScript"),
    # C should not falsely trigger on C++ or C#
    ("Expertise in C++ and C# but zero experience with plain C.", "C++", "C++"),
    # Node.js dot boundary
    ("Real-time messaging backend engineered using Node.js.", "Node.js", "Node.js"),
    # Negative contexts where skill is NOT possessed (should not produce conf >= 0.90)
    ("I have no experience with C or low-level systems programming.", "NONE", "C"),
    ("No knowledge of Java or related enterprise frameworks.", "NONE", "Java"),
]


def train_and_save_router(destination_path: str = ROUTER_PATH) -> Pipeline:
    """Trains a TF-IDF + LogisticRegression baseline router and persists to router.joblib."""
    texts = [item[0] for item in TRAIN_DATA]
    labels = [item[1] for item in TRAIN_DATA]

    # Token pattern that preserves symbol-aware tokens like C++, C#, .NET, Node.js
    token_pattern = r"(?u)\b[A-Za-z0-9_]+\b|\.NET|C\+\+|C\#|Node\.js"
    pipeline = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    token_pattern=token_pattern,
                    lowercase=False,
                ),
            ),
            (
                "clf",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1000,
                    C=1.0,
                    random_state=42,
                ),
            ),
        ]
    )

    pipeline.fit(texts, labels)
    os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)
    joblib.dump(pipeline, destination_path)
    return pipeline


def load_router(model_path: str = ROUTER_PATH) -> Pipeline:
    """Loads the persisted router.joblib, generating it if not present."""
    if not os.path.exists(model_path):
        return train_and_save_router(model_path)
    return joblib.load(model_path)


if __name__ == "__main__":
    train_and_save_router()
    print(f"Router baseline saved successfully to {ROUTER_PATH}")
