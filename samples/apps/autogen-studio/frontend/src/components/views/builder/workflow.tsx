import {
  InformationCircleIcon,
  PlusIcon,
  TrashIcon,
} from "@heroicons/react/24/outline";
import { Button, Dropdown, MenuProps, Modal, message } from "antd";
import * as React from "react";
import { IFlowConfig, IStatus } from "../../types";
import { appContext } from "../../../hooks/provider";
import {
  fetchJSON,
  getServerUrl,
  sampleWorkflowConfig,
  timeAgo,
  truncateText,
} from "../../utils";
import {
  Card,
  FlowConfigViewer,
  LaunchButton,
  LoadingOverlay,
} from "../../atoms";

const WorkflowView = ({}: any) => {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<IStatus | null>({
    status: true,
    message: "All good",
  });
  const { user } = React.useContext(appContext);
  const serverUrl = getServerUrl();
  const listWorkflowsUrl = `${serverUrl}/workflows?user_id=${user?.email}`;
  const saveWorkflowsUrl = `${serverUrl}/workflows`;
  const deleteWorkflowsUrl = `${serverUrl}/workflows/delete`;

  const [workflows, setWorkflows] = React.useState<IFlowConfig[] | null>([]);
  const [selectedWorkflow, setSelectedWorkflow] =
    React.useState<IFlowConfig | null>(null);

  const defaultConfig = sampleWorkflowConfig();
  const [newWorkflow, setNewWorkflow] = React.useState<IFlowConfig | null>(
    defaultConfig
  );

  const [showWorkflowModal, setShowWorkflowModal] = React.useState(false);
  const [showNewWorkflowModal, setShowNewWorkflowModal] = React.useState(false);

  const fetchWorkFlow = () => {
    setError(null);
    setLoading(true);
    // const fetch;
    const payLoad = {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
    };

    const onSuccess = (data: any) => {
      if (data && data.status) {
        message.success(data.message);
        console.log("workflows", data.data);
        setWorkflows(data.data);
      } else {
        message.error(data.message);
      }
      setLoading(false);
    };
    const onError = (err: any) => {
      setError(err);
      message.error(err.message);
      setLoading(false);
    };
    fetchJSON(listWorkflowsUrl, payLoad, onSuccess, onError);
  };

  const deleteWorkFlow = (workflow: IFlowConfig) => {
    setError(null);
    setLoading(true);
    // const fetch;
    const payLoad = {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: user?.email,
        workflow: workflow,
      }),
    };

    const onSuccess = (data: any) => {
      if (data && data.status) {
        message.success(data.message);
        setWorkflows(data.data);
      } else {
        message.error(data.message);
      }
      setLoading(false);
    };
    const onError = (err: any) => {
      setError(err);
      message.error(err.message);
      setLoading(false);
    };
    fetchJSON(deleteWorkflowsUrl, payLoad, onSuccess, onError);
  };

  const saveWorkFlow = (workflow: IFlowConfig) => {
    setError(null);
    setLoading(true);
    // const fetch;
    const payLoad = {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: user?.email,
        workflow: workflow,
      }),
    };

    const onSuccess = (data: any) => {
      if (data && data.status) {
        message.success(data.message);
        // console.log("workflows", data.data);
        setWorkflows(data.data);
      } else {
        message.error(data.message);
      }
      setLoading(false);
    };
    const onError = (err: any) => {
      setError(err);
      message.error(err.message);
      setLoading(false);
    };
    fetchJSON(saveWorkflowsUrl, payLoad, onSuccess, onError);
  };

  React.useEffect(() => {
    if (user) {
      // console.log("fetching messages", messages);
      fetchWorkFlow();
    }
  }, []);

  React.useEffect(() => {
    if (selectedWorkflow) {
      setShowWorkflowModal(true);
    }
  }, [selectedWorkflow]);

  const workflowRows = (workflows || []).map(
    (workflow: IFlowConfig, i: number) => {
      return (
        <div
          key={"workflowrow" + i}
          className="block   h-full"
          style={{ width: "200px" }}
        >
          <div className="  block">
            {" "}
            <Card
              className="  block p-2 cursor-pointer"
              title={
                <div className="  ">{truncateText(workflow.name, 25)}</div>
              }
              onClick={() => {
                setSelectedWorkflow(workflow);
              }}
            >
              <div style={{ minHeight: "45px" }} className="  my-2">
                {" "}
                {truncateText(workflow.name, 70)}
              </div>
              <div className="text-xs">{timeAgo(workflow.timestamp || "")}</div>
            </Card>
            <div className="text-right  mt-2">
              <div
                role="button"
                className="text-accent text-xs inline-block"
                onClick={() => {
                  deleteWorkFlow(workflow);
                }}
              >
                <TrashIcon className=" w-5, h-5 cursor-pointer inline-block" />
                <span className="text-xs"> delete</span>
              </div>
            </div>
          </div>
        </div>
      );
    }
  );

  const WorkflowModal = ({
    workflow,
    setWorkflow,
    showWorkflowModal,
    setShowWorkflowModal,
    handler,
  }: {
    workflow: IFlowConfig | null;
    setWorkflow?: (workflow: IFlowConfig | null) => void;
    showWorkflowModal: boolean;
    setShowWorkflowModal: (show: boolean) => void;
    handler?: (workflow: IFlowConfig) => void;
  }) => {
    const [localWorkflow, setLocalWorkflow] =
      React.useState<IFlowConfig | null>(workflow);

    return (
      <Modal
        title={
          <>
            Workflow Specification{" "}
            <span className="text-accent font-normal">
              {localWorkflow?.name}
            </span>{" "}
          </>
        }
        width={800}
        open={showWorkflowModal}
        onOk={() => {
          setShowWorkflowModal(false);
          if (handler) {
            handler(localWorkflow as IFlowConfig);
          }
        }}
        onCancel={() => {
          setShowWorkflowModal(false);
          setWorkflow?.(null);
        }}
      >
        {localWorkflow && (
          <FlowConfigViewer
            flowConfig={localWorkflow}
            setFlowConfig={setLocalWorkflow}
          />
        )}
      </Modal>
    );
  };

  const workflowTypes: MenuProps["items"] = [
    {
      key: "twoagents",
      label: "Two Agents",
    },
    {
      key: "groupchat",
      label: "Group Chat",
    },
  ];

  const workflowTypesOnClick: MenuProps["onClick"] = ({ key }) => {
    console.log("key", key);
    const newConfig = sampleWorkflowConfig(key);
    setNewWorkflow(newConfig);
    setShowNewWorkflowModal(true);
  };

  return (
    <div className=" text-primary ">
      <WorkflowModal
        workflow={selectedWorkflow}
        setWorkflow={setSelectedWorkflow}
        showWorkflowModal={showWorkflowModal}
        setShowWorkflowModal={setShowWorkflowModal}
        handler={(workflow: IFlowConfig) => {
          saveWorkFlow(workflow);
          setShowWorkflowModal(false);
        }}
      />

      <WorkflowModal
        workflow={newWorkflow}
        showWorkflowModal={showNewWorkflowModal}
        setShowWorkflowModal={setShowNewWorkflowModal}
        handler={(workflow: IFlowConfig) => {
          saveWorkFlow(workflow);
          setShowNewWorkflowModal(false);
        }}
      />

      <div className="mb-2   relative">
        <div className="     rounded  ">
          <div className="flex mt-2 pb-2 mb-2 border-b">
            <div className="flex-1 font-semibold  mb-2 ">
              {" "}
              Workflows ({workflowRows.length}){" "}
            </div>
            <div className=" ">
              <Dropdown
                menu={{ items: workflowTypes, onClick: workflowTypesOnClick }}
                placement="bottomRight"
              >
                <div
                  className="inline-flex mr-1 mb-1 p-1 px-2 rounded   hover:border-accent duration-300 hover:text-accent"
                  role="button"
                  onClick={(e) => {
                    // add agent to flowSpec?.groupchat_config.agents
                  }}
                >
                  <LaunchButton className="-mt-2 text-sm p-2 px-3">
                    {" "}
                    <PlusIcon className="w-5 h-5 inline-block mr-1" />
                    New Workflow
                  </LaunchButton>
                </div>
              </Dropdown>
            </div>
          </div>

          <div className="text-xs mb-2 pb-1  ">
            {" "}
            Configure an agent workflow that can be used to handle tasks.
          </div>
          {workflows && workflows.length > 0 && (
            <div
              // style={{ minHeight: "500px" }}
              className="w-full relative"
            >
              <LoadingOverlay loading={loading} />
              <div className="flex flex-wrap gap-3">{workflowRows}</div>
            </div>
          )}

          {workflows && workflows.length === 0 && !loading && (
            <div className="text-sm border mt-4 rounded text-secondary p-2">
              <InformationCircleIcon className="h-4 w-4 inline mr-1" />
              No workflows found. Please create a new workflow.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default WorkflowView;
