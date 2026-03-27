import { Layout, Space } from "antd";
import LanguageSwitcher from "../components/LanguageSwitcher";
import ThemeToggleButton from "../components/ThemeToggleButton";
import AgentSelector from "../components/AgentSelector";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";
import { KEY_TO_LABEL } from "./constants";

const { Header: AntHeader } = Layout;

interface HeaderProps {
  selectedKey: string;
}

export default function Header({ selectedKey }: HeaderProps) {
  const { t } = useTranslation();

  return (
    <AntHeader className={styles.header}>
      <div className={styles.headerLeft}>
        <span className={styles.headerTitle}>
          {t(KEY_TO_LABEL[selectedKey] || "nav.chat")}
        </span>
      </div>
      <div className={styles.headerCenter}>
        <AgentSelector />
      </div>
      <Space size="middle" className={styles.headerRight}>
        <LanguageSwitcher />
        <ThemeToggleButton />
      </Space>
    </AntHeader>
  );
}
