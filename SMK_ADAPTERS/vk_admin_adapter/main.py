import os


def main() -> None:
    os.environ["VK_ADAPTER_ROLE"] = "ADMIN"

    from SMK_ADAPTERS.vk_adapter.main import main as runVkAdapter

    runVkAdapter()


if __name__ == "__main__":
    main()
