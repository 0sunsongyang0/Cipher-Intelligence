import { getFileIconAsset } from "../../lib/fileIcons";

type AttachmentTypeIconProps = {
  className?: string;
  name: string;
  type: string;
};

export function AttachmentTypeIcon({ className, name, type }: AttachmentTypeIconProps) {
  const icon = getFileIconAsset(name, type);

  return (
    <span
      className={className}
      data-file-icon={icon.name}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: icon.svg }}
    />
  );
}
