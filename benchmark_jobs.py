import time
import timeit

class MockJob:
    def __init__(self, name):
        self.name = name

class MockJobQueue:
    def __init__(self):
        self._jobs = []

    def add_job(self, job):
        self._jobs.append(job)

    def get_jobs_by_name(self, name):
        # Simulate O(N) lookup
        return [job for job in self._jobs if job.name == name]

def setup_benchmark(num_jobs):
    queue = MockJobQueue()
    chat_data = {}

    # Add dummy jobs
    for i in range(num_jobs):
        queue.add_job(MockJob(f"dummy_job_{i}"))

    # Add target job
    target_job = MockJob("target_job")
    queue.add_job(target_job)
    chat_data["target_job"] = target_job

    return queue, chat_data

def test_get_jobs_by_name(queue):
    for job in queue.get_jobs_by_name("target_job"):
        pass

def test_dict_lookup(chat_data):
    job = chat_data.get("target_job")
    if job:
        pass

if __name__ == "__main__":
    num_jobs = 50
    queue, chat_data = setup_benchmark(num_jobs)

    # Run benchmarks
    iterations = 100000

    time_o_n = timeit.timeit(lambda: test_get_jobs_by_name(queue), number=iterations)
    time_o_1 = timeit.timeit(lambda: test_dict_lookup(chat_data), number=iterations)

    print(f"Benchmark results ({iterations} iterations, {num_jobs} background jobs):")
    print(f"O(N) `get_jobs_by_name`: {time_o_n:.4f} seconds")
    print(f"O(1) dictionary lookup: {time_o_1:.4f} seconds")
    print(f"Improvement: {time_o_n / time_o_1:.2f}x faster")
